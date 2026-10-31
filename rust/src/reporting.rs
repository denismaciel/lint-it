use crate::{engine::Result, model::Finding, workspace::Workspace};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};
#[derive(Deserialize)]
pub struct Rule {
    pub code: String,
    pub name: String,
    pub documentation: String,
}
pub fn registry() -> &'static [Rule] {
    static RULES: std::sync::OnceLock<Vec<Rule>> = std::sync::OnceLock::new();
    RULES.get_or_init(|| serde_json::from_str(include_str!("registry.json")).unwrap())
}
pub fn rule(name: &str) -> Option<&'static Rule> {
    registry()
        .iter()
        .find(|r| r.code == name.to_uppercase() || r.name == name)
}
#[derive(Serialize)]
pub struct Summary {
    pub packages: usize,
    pub files: usize,
    pub baselined: usize,
    pub ignored: usize,
}
fn plural(n: usize, noun: &str) -> String {
    format!("{n} {noun}{}", if n == 1 { "" } else { "s" })
}
fn escape(s: &str, property: bool) -> String {
    let s = s
        .replace('%', "%25")
        .replace('\r', "%0D")
        .replace('\n', "%0A");
    if property {
        s.replace(':', "%3A").replace(',', "%2C")
    } else {
        s
    }
}
pub fn report(findings: &[Finding], summary: Option<&Summary>, format: &str) -> String {
    if format == "json" {
        let mut totals = summary.map_or(json!({}), |s| json!(s));
        totals["findings"] = json!(findings.len());
        return serde_json::to_string_pretty(&json!({"findings":findings,"summary":totals}))
            .unwrap();
    }
    if format == "github" {
        return findings
            .iter()
            .map(|f| {
                format!(
                    "::error file={},line={},col={},title={}::{}",
                    escape(&f.filename, true),
                    f.line,
                    f.column + 1,
                    f.code,
                    escape(&f.message, false)
                )
            })
            .collect::<Vec<_>>()
            .join("\n");
    }
    let mut lines: Vec<_> = findings
        .iter()
        .map(|f| {
            format!(
                "{}:{}:{}: {} {}",
                f.filename,
                f.line,
                f.column + 1,
                f.code,
                f.message
            )
        })
        .collect();
    if let Some(s) = summary {
        let mut checked = format!(
            "{} in {} checked",
            plural(s.files, "file"),
            plural(s.packages, "package")
        );
        let suppressed: Vec<_> = [(s.baselined, "baselined"), (s.ignored, "ignored")]
            .iter()
            .filter(|(n, _)| *n > 0)
            .map(|(n, label)| format!("{n} {label}"))
            .collect();
        if !suppressed.is_empty() {
            checked.push_str(&format!("; {}", suppressed.join(", ")));
        }
        lines.push(if findings.is_empty() {
            format!("No findings ({checked})")
        } else {
            format!(
                "{} in {} ({checked})",
                plural(findings.len(), "finding"),
                plural(
                    findings
                        .iter()
                        .map(|f| &f.filename)
                        .collect::<BTreeSet<_>>()
                        .len(),
                    "file"
                )
            )
        });
    }
    lines.join("\n")
}
fn ranked(labels: impl Iterator<Item = String>, top: usize) -> Value {
    let mut counts: Vec<(String, usize)> = Vec::new();
    let mut positions = BTreeMap::new();
    for label in labels {
        let idx = *positions.entry(label.clone()).or_insert_with(|| {
            counts.push((label, 0));
            counts.len() - 1
        });
        counts[idx].1 += 1;
    }
    counts.sort_by_key(|(_, n)| std::cmp::Reverse(*n));
    json!(
        counts
            .into_iter()
            .take(top)
            .map(|(label, findings)| json!({"label":label,"findings":findings}))
            .collect::<Vec<_>>()
    )
}
pub fn statistics(result: &Result, w: &Workspace, top: usize, depth: usize) -> Value {
    let findings: Vec<_> = result.findings.iter().chain(&result.baselined).collect();
    let mut rules: BTreeMap<String, (usize, usize, BTreeSet<String>)> = BTreeMap::new();
    for f in &findings {
        let row = rules.entry(f.code.clone()).or_default();
        row.0 += 1;
        row.2.insert(f.filename.clone());
    }
    for f in &result.findings {
        rules.get_mut(&f.code).unwrap().1 += 1;
    }
    let mut rules: Vec<_> = rules.into_iter().collect();
    rules.sort_by(|a, b| b.1.0.cmp(&a.1.0).then(a.0.cmp(&b.0)));
    let layer = |path: Option<&std::path::Path>| {
        path.and_then(|p| w.classify(p))
            .map_or("unclassified".into(), |c| c.name)
    };
    json!({"findings":findings.len(),"new":result.findings.len(),"baselined":result.baselined.len(),"ignored":result.ignored.len(),
      "rules":rules.iter().map(|(code,(count,new,files))|json!({"code":code,"name":rule(code).map_or(code.as_str(),|r|r.name.as_str()),"findings":count,"new":new,"files":files.len()})).collect::<Vec<_>>(),
      "edges":ranked(findings.iter().filter(|f|f.code=="LIT101"&&f.target.is_some()).map(|f|format!("{} -> {}",layer(Some(&w.root.join(&f.filename))),layer(w.module_source(f.target.as_ref().unwrap()).map(|s|s.path.as_path())))),top),
      "targets":ranked(findings.iter().filter_map(|f|f.target.as_ref().filter(|t|!t.is_empty()).map(|t|format!("{} {t}",f.code))),top),
      "areas":ranked(findings.iter().map(|f|{let mut parts:Vec<_>=f.filename.split('/').collect();parts.pop();let area=parts.into_iter().take(depth).collect::<Vec<_>>().join("/");if area.is_empty(){".".into()}else{area}}),top)})
}
pub fn render_statistics(stats: &Value, format: &str) -> String {
    if format == "json" {
        return serde_json::to_string_pretty(stats).unwrap();
    }
    let mut lines = vec![
        format!(
            "{}: {} new, {} baselined ({} ignored)",
            plural(stats["findings"].as_u64().unwrap() as usize, "finding"),
            stats["new"],
            stats["baselined"],
            stats["ignored"]
        ),
        "".into(),
        "By rule".into(),
    ];
    for r in stats["rules"].as_array().unwrap() {
        lines.push(format!(
            "  {}  {:<22} {:>6}  {:>6} new  {}",
            r["code"].as_str().unwrap(),
            r["name"].as_str().unwrap(),
            r["findings"].as_u64().unwrap(),
            r["new"].as_u64().unwrap(),
            plural(r["files"].as_u64().unwrap() as usize, "file")
        ));
    }
    for (title, key) in [
        ("Layer edges (LIT101)", "edges"),
        ("Top targets", "targets"),
        ("Top areas", "areas"),
    ] {
        let counts = stats[key].as_array().unwrap();
        if !counts.is_empty() {
            lines.extend(["".into(), title.into()]);
            for c in counts {
                lines.push(format!(
                    "  {:>6}  {}",
                    c["findings"].as_u64().unwrap(),
                    c["label"].as_str().unwrap()
                ));
            }
        }
    }
    lines.join("\n")
}
