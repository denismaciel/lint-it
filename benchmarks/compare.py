"""Pinned real-world differential benchmark; never runs code from the corpus."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import platform
import statistics
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = """[workspace]
kind = "library"
layout = "benchmark"

[layouts.benchmark]
layers = [
  { glob = "**/*.py", layer = "core" },
  { glob = "tests/**/*.py", layer = "test" },
  { glob = "**/tests/**/*.py", layer = "test" },
  { glob = "examples/**/*.py", layer = "boundary" },
  { glob = "**/__init__.py", layer = "marker" },
]
"""


def prepare(project: dict, destination: Path) -> Path:
    path = destination / project["name"]
    marker = path / ".benchmark-revision"
    if marker.exists():
        if marker.read_text() != project["revision"]:
            raise ValueError(f"wrong revision at {path}; use a fresh --work directory")
        return path
    url = f"https://codeload.github.com/{project['repository']}/tar.gz/{project['revision']}"
    print(f"Downloading {project['name']} {project['revision']}", flush=True)
    data = urllib.request.urlopen(url, timeout=120).read()
    path.mkdir(parents=True, exist_ok=True)
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        for member in archive.getmembers():
            relative = Path(*Path(member.name).parts[1:])
            if not relative.parts:
                continue
            member.name = str(relative)
            archive.extract(member, path, filter="data")
    # Same explicit policy for both tools, avoiding a vacuous all-unclassified run.
    (path / "lint-it.toml").write_text(MANIFEST)
    if not (path / "pyproject.toml").exists():
        (path / "pyproject.toml").write_text('[project]\nname = "benchmark"\n')
    marker.write_text(project["revision"])
    return path


def invoke(command: list[str]) -> tuple[float, dict, int]:
    start = time.perf_counter()
    p = subprocess.run(command, capture_output=True, text=True, check=False, cwd=ROOT)
    elapsed = time.perf_counter() - start
    if p.returncode not in (0, 1):
        raise RuntimeError(f"{command}: exit {p.returncode}\n{p.stderr}\n{p.stdout[:2000]}")
    return elapsed, json.loads(p.stdout), p.returncode


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work", type=Path, default=ROOT / "benchmarks/target")
    parser.add_argument("--binary", type=Path, default=ROOT / "rust/target/release/lint-it-rust")
    parser.add_argument("--runs", type=int, default=7)
    parser.add_argument("--jobs", type=int, nargs="+", default=[1, 4])
    parser.add_argument("--project", action="append")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--output", type=Path, default=ROOT / "benchmarks/results.json")
    args = parser.parse_args()
    projects = json.loads((ROOT / "benchmarks/projects.json").read_text())
    if args.runs < 1 or any(j < 1 for j in args.jobs):
        parser.error("--runs and --jobs must be positive")
    report = {
        "platform": platform.platform(),
        "python": sys.version,
        "cpu_count": os.cpu_count(),
        "runs": args.runs,
        "binary_sha256": (
            hashlib.sha256(args.binary.read_bytes()).hexdigest() if args.binary.exists() else None
        ),
        "rustc": subprocess.check_output(["rustc", "--version"], text=True).strip(),
        "reference_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "cpu": next(
            (
                line.split(":", 1)[1].strip()
                for line in Path("/proc/cpuinfo").read_text().splitlines()
                if line.startswith("model name")
            ),
            "unknown",
        )
        if Path("/proc/cpuinfo").exists()
        else platform.processor(),
        "method": (
            "warm filesystem; fresh process; alternating order; "
            "no analysis cache; complete JSON equality"
        ),
        "results": [],
    }
    for project in projects:
        if args.project and project["name"] not in args.project:
            continue
        path = prepare(project, args.work.resolve())
        if args.prepare_only:
            continue
        files = sorted(path.rglob("*.py"))
        digest = hashlib.sha256()
        for file in files:
            digest.update(str(file.relative_to(path)).encode() + b"\0" + file.read_bytes())
        for jobs in args.jobs:
            options = ["check", "--root", str(path), "--format", "json", "--jobs", str(jobs)]
            commands = {
                "python": [sys.executable, "-m", "lint_it", *options],
                "rust": [str(args.binary.resolve()), *options],
            }
            # Warm up and require complete diagnostics and summary equality BEFORE timing.
            _, expected, expected_exit = invoke(commands["python"])
            _, actual, actual_exit = invoke(commands["rust"])
            if (expected, expected_exit) != (actual, actual_exit):
                for name, value in [("python", expected), ("rust", actual)]:
                    (args.work / f"{project['name']}-{name}.json").write_text(
                        json.dumps(value, indent=2)
                    )
                raise AssertionError(f"{project['name']}: outputs differ; inspect {args.work}")
            timings = {name: [] for name in commands}
            for index in range(args.runs):
                order = list(commands)
                if index % 2:
                    order.reverse()
                for name in order:
                    elapsed, result, exit_code = invoke(commands[name])
                    if (result, exit_code) != (expected, expected_exit):
                        raise AssertionError(f"{project['name']}: nondeterministic output ({name})")
                    timings[name].append(elapsed)
            medians = {name: statistics.median(values) for name, values in timings.items()}
            row = {
                **project,
                "jobs": jobs,
                "files": expected["summary"]["files"],
                "source_bytes": sum(f.stat().st_size for f in files),
                "source_sha256": digest.hexdigest(),
                "policy_sha256": hashlib.sha256(MANIFEST.encode()).hexdigest(),
                "findings": len(expected["findings"]),
                "equivalent": True,
                "output_sha256": hashlib.sha256(
                    json.dumps(expected, sort_keys=True).encode()
                ).hexdigest(),
                "seconds": timings,
                "median_seconds": medians,
                "speedup": medians["python"] / medians["rust"],
            }
            report["results"].append(row)
            print(
                f"{project['name']} jobs={jobs}: {row['files']} files, {row['findings']} findings, "
                f"Python {medians['python']:.3f}s / Rust {medians['rust']:.3f}s "
                f"= {row['speedup']:.2f}x",
                flush=True,
            )
            args.output.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
