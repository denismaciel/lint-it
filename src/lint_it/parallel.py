"""Rule checks spread over forked workers that inherit the parsed snapshot."""

from __future__ import annotations

import multiprocessing
import os
import traceback
from collections.abc import Sequence
from multiprocessing.connection import Connection

from lint_it.core import Finding, Rule
from lint_it.engine import FileChecker, check_files
from lint_it.workspace import Source, Workspace


def _available_cpus() -> int:
    if hasattr(os, "sched_getaffinity"):
        return len(os.sched_getaffinity(0))
    return os.cpu_count() or 1


def _work(
    sender: Connection, workspace: Workspace, rules: tuple[Rule, ...], sources: Sequence[Source]
) -> None:
    try:
        sender.send(check_files(workspace, rules, sources))
    except BaseException:
        sender.send(traceback.format_exc())
    finally:
        sender.close()


def checker(jobs: int | None, files_per_job: int = 150) -> FileChecker:
    """A file checker over ``jobs`` processes (default: every available CPU), with
    at least ``files_per_job`` files each: below that, forking costs more than it saves.

    Falls back to checking in-process where ``fork`` is unavailable, since a
    spawned worker would have to load and parse the workspace again.
    """

    def check(
        workspace: Workspace, rules: tuple[Rule, ...], sources: Sequence[Source]
    ) -> list[Finding]:
        count = min(jobs or _available_cpus(), len(sources) // files_per_job)
        if count < 2 or "fork" not in multiprocessing.get_all_start_methods():
            return check_files(workspace, rules, sources)
        context = multiprocessing.get_context("fork")
        workers = []
        for index in range(count):
            receiver, sender = context.Pipe(duplex=False)
            process = context.Process(
                target=_work, args=(sender, workspace, rules, sources[index::count])
            )
            process.start()
            sender.close()
            workers.append((process, receiver))
        findings: list[Finding] = []
        failures: list[str] = []
        for process, receiver in workers:
            try:
                result: list[Finding] | str = receiver.recv()
            except EOFError:
                process.join()
                result = f"worker exited with status {process.exitcode}"
            process.join()
            if isinstance(result, str):
                failures.append(result)
            else:
                findings.extend(result)
        if failures:
            raise RuntimeError("lint-it worker failed:\n" + "\n".join(failures))
        return findings

    return check
