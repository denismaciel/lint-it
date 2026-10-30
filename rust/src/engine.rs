use crate::{
    model::{Finding, relative_name},
    reporting::registry,
    workspace::{Workspace, matches_glob},
};
use rayon::prelude::*;
use std::{
    collections::{BTreeMap, BTreeSet},
    path::{Path, PathBuf},
};
#[derive(Default)]
pub struct Result {
    pub findings: Vec<Finding>,
    pub baselined: Vec<Finding>,
    pub ignored: Vec<Finding>,
}
pub fn key(f: &Finding) -> (String, String, String) {
    (f.filename.clone(), f.code.clone(), f.message.clone())
}
pub fn sort(findings: &mut Vec<Finding>) {
    findings.sort();
    findings.dedup();
}
pub fn run(w: &Workspace, selected: &[PathBuf], no_baseline: bool) -> Result {
    let selected_path = |p: &Path| selected.is_empty() || selected.iter().any(|s| p.starts_with(s));
    let manifest = w
        .manifest
        .as_ref()
        .map_or("lint-it.toml".into(), |p| relative_name(p, &w.root));
    let problem = |message: String| Finding {
        filename: manifest.clone(),
        line: 1,
        column: 0,
        code: "LIT003".into(),
        message,
        target: None,
    };
    let mut problems: Vec<_> = w.configuration_errors().into_iter().map(&problem).collect();
    for (path, error) in &w.parse_failures {
        if selected_path(path) {
            problems.push(Finding {
                filename: relative_name(path, &w.root),
                line: error.line,
                column: error.column,
                code: "LIT001".into(),
                message: format!("file cannot be parsed: {}", error.message),
                target: None,
            });
        }
    }
    let mut found: Vec<_> = w
        .sources
        .par_iter()
        .filter(|s| selected_path(&s.path))
        .flat_map_iter(|s| {
            let mut f = crate::rules::check(s, w);
            f.extend(crate::dependencies::check(s, w));
            f
        })
        .collect();
    sort(&mut found);
    let mut ignores = Vec::new();
    for ignore in &w.ignores {
        let mut codes = BTreeSet::new();
        for name in &ignore.rules {
            match registry()
                .iter()
                .find(|r| r.code == *name || r.name == *name)
            {
                None => problems.push(problem(format!("ignore names unknown rule {name}"))),
                Some(r) if ["LIT001", "LIT003"].contains(&r.code.as_str()) => {
                    problems.push(problem(format!("{} cannot be ignored", r.code)))
                }
                Some(r) => {
                    codes.insert(r.code.clone());
                }
            }
        }
        ignores.push((ignore, codes));
    }
    let mut used = BTreeSet::new();
    let mut kept = Vec::new();
    let mut ignored = Vec::new();
    for f in found {
        let matched = ignores.iter().position(|(i, codes)| {
            codes.contains(&f.code)
                && (i.paths.is_empty() || i.paths.iter().any(|p| matches_glob(&f.filename, p)))
                && (i.layers.is_empty()
                    || w.classify(&w.root.join(&f.filename))
                        .is_some_and(|c| w.policy.is_a(&c.name, &i.layers)))
        });
        if let Some(i) = matched {
            used.insert(i);
            ignored.push(f);
        } else {
            kept.push(f);
        }
    }
    if selected.is_empty() {
        for (index, (i, codes)) in ignores.iter().enumerate() {
            if !used.contains(&index) && !codes.is_empty() {
                let mut scope = i.paths.clone();
                scope.extend(i.layers.iter().cloned());
                let description = if scope.is_empty() {
                    i.rules.join(", ")
                } else {
                    format!("{} in {}", i.rules.join(", "), scope.join(", "))
                };
                problems.push(problem(format!("ignore suppresses nothing: {description}")));
            }
        }
    }
    let mut baselined = Vec::new();
    if let Some(baseline_path) = w.baseline_path.as_ref().filter(|_| !no_baseline) {
        let mut remaining: BTreeMap<_, _> = w.baseline.clone();
        for f in kept {
            let count = remaining.entry(key(&f)).or_default();
            if *count > 0 {
                *count -= 1;
                baselined.push(f);
            } else {
                problems.push(f);
            }
        }
        let stale: usize = remaining
            .iter()
            .filter(|((filename, _, _), _)| selected_path(&w.root.join(filename)))
            .map(|(_, n)| n)
            .sum();
        if stale > 0 {
            problems.push(Finding {filename:relative_name(baseline_path,&w.root),line:1,column:0,code:"LIT003".into(),message:format!("{stale} baseline {} no longer {} a finding; run `lint-it baseline --prune` to shrink the baseline",if stale==1{"entry"}else{"entries"},if stale==1{"matches"}else{"match"}),target:None});
        }
    } else {
        problems.extend(kept);
    }
    sort(&mut problems);
    Result {
        findings: problems,
        baselined,
        ignored,
    }
}
