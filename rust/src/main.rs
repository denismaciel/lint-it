#[cfg(unix)]
#[global_allocator]
static GLOBAL: tikv_jemallocator::Jemalloc = tikv_jemallocator::Jemalloc;

use clap::{Parser, Subcommand};
use lint_it_rust::{
    engine,
    model::{Finding, relative_name},
    reporting, workspace,
};
use std::{
    collections::{BTreeMap, BTreeSet},
    path::{Path, PathBuf},
    process::ExitCode,
};
#[derive(Parser)]
#[command(
    name = "lint-it",
    about = "Architecture rules for functional-core Python workspaces."
)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}
#[derive(Subcommand)]
enum Command {
    Check {
        paths: Vec<PathBuf>,
        #[arg(long)]
        root: Option<PathBuf>,
        #[arg(long,default_value="text",value_parser=["text","json","github"])]
        format: String,
        #[arg(long,value_parser=clap::value_parser!(u16).range(1..))]
        jobs: Option<u16>,
        #[arg(long)]
        no_baseline: bool,
    },
    Report {
        paths: Vec<PathBuf>,
        #[arg(long)]
        root: Option<PathBuf>,
        #[arg(long,default_value="text",value_parser=["text","json"])]
        format: String,
        #[arg(long, default_value_t = 15)]
        top: usize,
        #[arg(long, default_value_t = 3)]
        depth: usize,
        #[arg(long)]
        rule: Vec<String>,
        #[arg(long,value_parser=clap::value_parser!(u16).range(1..))]
        jobs: Option<u16>,
    },
    Baseline {
        #[arg(long)]
        root: Option<PathBuf>,
        #[arg(long)]
        prune: bool,
        #[arg(long,value_parser=clap::value_parser!(u16).range(1..))]
        jobs: Option<u16>,
    },
    Classify {
        #[arg(required = true)]
        paths: Vec<PathBuf>,
        #[arg(long)]
        root: Option<PathBuf>,
    },
    Explain {
        code: String,
    },
    Rules {
        #[arg(long,default_value="text",value_parser=["text","markdown"])]
        format: String,
    },
    Init {
        #[arg(long, default_value = ".")]
        root: PathBuf,
        #[arg(long,default_value="server",value_parser=["server","client","library"])]
        kind: String,
        #[arg(long,default_value="domains",value_parser=["domains","hexagonal","flat","boundary","test-support"])]
        layout: String,
    },
}
fn absolute(path: &Path) -> PathBuf {
    std::path::absolute(path).unwrap_or_else(|_| path.to_path_buf())
}
fn load(root: Option<PathBuf>, format: &str) -> Result<workspace::Workspace, ()> {
    let root = root.map_or_else(
        || workspace::find_root(&std::env::current_dir().unwrap()),
        |p| absolute(&p),
    );
    match workspace::load(&root) {
        Ok(w) => Ok(w),
        Err(message) => {
            let p = Finding {
                filename: "lint-it.toml".into(),
                line: 1,
                column: 0,
                code: "LIT003".into(),
                message,
                target: None,
            };
            let output = reporting::report(&[p], None, format);
            if format == "text" {
                eprintln!("{output}")
            } else {
                println!("{output}")
            };
            Err(())
        }
    }
}
fn selected(paths: &[PathBuf], root: &Path) -> Result<Vec<PathBuf>, String> {
    paths
        .iter()
        .map(|p| {
            let p = absolute(p);
            if !p.exists() {
                return Err(format!("no such file or directory: {}", p.display()));
            }
            let p = p.canonicalize().map_err(|e| e.to_string())?;
            if !p.starts_with(root) {
                return Err(format!(
                    "{} is outside the workspace {}",
                    p.display(),
                    root.display()
                ));
            }
            Ok(p)
        })
        .collect()
}
fn set_jobs(jobs: Option<u16>) -> Result<(), String> {
    if let Some(n) = jobs {
        rayon::ThreadPoolBuilder::new()
            .num_threads(n as usize)
            .build_global()
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}
fn execute(command: Command) -> Result<u8, String> {
    let _span = lint_it_rust::profile::span("command");
    match command {
        Command::Check {
            paths,
            root,
            format,
            jobs,
            no_baseline,
        } => {
            set_jobs(jobs)?;
            let Ok(w) = load(root, &format) else {
                return Ok(2);
            };
            let paths = selected(&paths, &w.root)?;
            let result = engine::run(&w, &paths, no_baseline);
            let totals = reporting::Summary {
                packages: w.packages.len(),
                files: w.sources.len() + w.parse_failures.len(),
                baselined: result.baselined.len(),
                ignored: result.ignored.len(),
            };
            let output = reporting::report(&result.findings, Some(&totals), &format);
            if !output.is_empty() {
                println!("{output}")
            };
            let exit_code = u8::from(!result.findings.is_empty());
            let drop_span = lint_it_rust::profile::span("workspace_drop");
            drop(w);
            drop(drop_span);
            Ok(exit_code)
        }
        Command::Report {
            paths,
            root,
            format,
            top,
            depth,
            rule,
            jobs,
        } => {
            set_jobs(jobs)?;
            let Ok(w) = load(root, &format) else {
                return Ok(2);
            };
            let paths = selected(&paths, &w.root)?;
            let codes: Result<BTreeSet<_>, _> = rule
                .iter()
                .map(|n| {
                    reporting::rule(n)
                        .map(|r| r.code.clone())
                        .ok_or("unknown rule; run `lint-it rules`".to_owned())
                })
                .collect();
            let codes = codes?;
            let mut result = engine::run(&w, &paths, false);
            if !codes.is_empty() {
                result.findings.retain(|f| codes.contains(&f.code));
                result.baselined.retain(|f| codes.contains(&f.code));
                result.ignored.retain(|f| codes.contains(&f.code));
            }
            println!(
                "{}",
                reporting::render_statistics(
                    &reporting::statistics(&result, &w, top, depth),
                    &format
                )
            );
            Ok(0)
        }
        Command::Baseline { root, prune, jobs } => {
            set_jobs(jobs)?;
            let Ok(w) = load(root, "text") else {
                return Ok(2);
            };
            let Some(path) = &w.baseline_path else {
                return Err("set workspace.baseline in lint-it.toml, e.g. baseline = \"lint-it-baseline.json\"".into());
            };
            let result = engine::run(&w, &[], true);
            let mut actual = BTreeMap::new();
            let mut problems = Vec::new();
            for f in result.findings {
                if ["LIT001", "LIT003"].contains(&f.code.as_str()) {
                    problems.push(f)
                } else {
                    *actual.entry(engine::key(&f)).or_insert(0usize) += 1;
                }
            }
            let counts = if prune {
                w.baseline
                    .iter()
                    .map(|(k, n)| (k.clone(), (*n).min(*actual.get(k).unwrap_or(&0))))
                    .collect()
            } else {
                actual
            };
            std::fs::write(path, render_baseline(&counts)).map_err(|e| e.to_string())?;
            let recorded: usize = counts.values().sum();
            let files = counts
                .iter()
                .filter(|(_, n)| **n > 0)
                .map(|((f, _, _), _)| f)
                .collect::<BTreeSet<_>>()
                .len();
            println!(
                "wrote {}: {recorded} findings in {files} files (was {})",
                relative_name(path, &w.root),
                w.baseline.values().sum::<usize>()
            );
            if !problems.is_empty() {
                eprintln!("{}", reporting::report(&problems, None, "text"));
                Ok(1)
            } else {
                Ok(0)
            }
        }
        Command::Classify { paths, root } => {
            let Ok(w) = load(root, "text") else {
                return Ok(2);
            };
            let paths = selected(&paths, &w.root)?;
            let known: BTreeSet<_> = w
                .sources
                .iter()
                .map(|s| s.path.clone())
                .chain(w.parse_failures.iter().map(|(p, _)| p.clone()))
                .chain(paths.iter().filter(|p| p.is_file()).cloned())
                .collect();
            for path in known {
                if !paths.iter().any(|p| path.starts_with(p)) {
                    continue;
                }
                let name = relative_name(&path, &w.root);
                let package = w
                    .packages
                    .iter()
                    .filter(|p| path.starts_with(&p.root))
                    .max_by_key(|p| p.root.components().count());
                let Some(package) = package else {
                    println!("{name}: outside every package");
                    continue;
                };
                let Some(c) = w.classify(&path) else {
                    println!("{name}: unclassified ({} layout)", package.layout);
                    continue;
                };
                let origin = if c.origin == "override" {
                    "override".into()
                } else {
                    format!("{} layout", package.layout)
                };
                let layer = if c.layer == c.name {
                    c.name
                } else {
                    format!("{} (a {})", c.name, c.layer)
                };
                println!("{name}: {layer} ({origin}, {})", c.glob);
            }
            Ok(0)
        }
        Command::Explain { code } => {
            let r = reporting::rule(&code)
                .ok_or_else(|| format!("unknown rule {code}; run `lint-it rules`"))?;
            println!("{} {}\n\n{}", r.code, r.name, r.documentation);
            Ok(0)
        }
        Command::Rules { format } => {
            if format == "markdown" {
                print!("{}", include_str!("../../docs/rules.md"));
            } else {
                for r in reporting::registry() {
                    println!(
                        "{}  {:<22}  {}",
                        r.code,
                        r.name,
                        r.documentation.lines().next().unwrap_or("")
                    );
                }
            }
            Ok(0)
        }
        Command::Init { root, kind, layout } => {
            use std::io::Write;
            let path: PathBuf = root
                .join("lint-it.toml")
                .components()
                .filter(|c| !matches!(c, std::path::Component::CurDir))
                .collect();
            let mut file = std::fs::OpenOptions::new()
                .write(true)
                .create_new(true)
                .open(&path)
                .map_err(|e| {
                    if e.kind() == std::io::ErrorKind::AlreadyExists {
                        format!("{} already exists", path.display())
                    } else {
                        e.to_string()
                    }
                })?;
            write!(file,"# lint-it manifest: https://github.com/denismaciel/lint-it/blob/main/docs/configuration.md\n\n[workspace]\nkind = \"{kind}\"\nlayout = \"{layout}\"\n").map_err(|e|e.to_string())?;
            println!("wrote {}; run `lint-it check` next", path.display());
            Ok(0)
        }
    }
}
fn render_baseline(counts: &BTreeMap<(String, String, String), usize>) -> String {
    let mut files: BTreeMap<&str, Vec<String>> = BTreeMap::new();
    for ((filename, code, message), count) in counts {
        if *count > 0 {
            files.entry(filename).or_default().push(format!(
                "{{\"code\": {}, \"message\": {}, \"count\": {count}}}",
                serde_json::to_string(code).unwrap(),
                serde_json::to_string(message).unwrap()
            ));
        }
    }
    let blocks: Vec<_> = files
        .iter()
        .map(|(filename, entries)| {
            format!(
                "    {}: [\n      {}\n    ]",
                serde_json::to_string(filename).unwrap(),
                entries.join(",\n      ")
            )
        })
        .collect();
    let body = if blocks.is_empty() {
        "{}".into()
    } else {
        format!("{{\n{}\n  }}", blocks.join(",\n"))
    };
    format!("{{\n  \"version\": 1,\n  \"findings\": {body}\n}}\n")
}
fn main() -> ExitCode {
    let result = execute(Cli::parse().command);
    lint_it_rust::profile::print();
    match result {
        Ok(code) => ExitCode::from(code),
        Err(error) => {
            eprintln!("lint-it: {error}");
            ExitCode::from(2)
        }
    }
}
