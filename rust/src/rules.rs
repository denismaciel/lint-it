use crate::{
    ast::{self, Node, child, items, kind, s, walk},
    model::{Finding, Source, finding},
    symbols,
    workspace::Workspace,
};
use std::collections::{BTreeSet, HashMap, HashSet};
mod ambient;
mod capabilities;
mod defaults;
mod effects;
mod mutation;
mod simple;
mod subclass;
fn joined(names: &BTreeSet<String>) -> String {
    names.iter().cloned().collect::<Vec<_>>().join(", ")
}
fn names(file: &Source, node: &Node) -> BTreeSet<String> {
    symbols::names(&file.symbols, node)
}
fn add(out: &mut Vec<Finding>, file: &Source, node: &Node, code: &str, msg: impl Into<String>) {
    out.push(finding(file, node, code, msg, None));
}
fn parameters(node: &Node) -> Vec<&Node> {
    let args = child(node, "args");
    ["posonlyargs", "args", "kwonlyargs"]
        .iter()
        .flat_map(|k| items(args, k))
        .collect()
}
fn children(node: &Node) -> Vec<&Node> {
    let mut out = Vec::new();
    if let Some(map) = node.as_object() {
        for (k, v) in map {
            if k.starts_with('_') {
                continue;
            }
            if v.get("_type").is_some() {
                out.push(v)
            } else if let Some(a) = v.as_array() {
                out.extend(a.iter().filter(|x| x.get("_type").is_some()));
            }
        }
    }
    out
}
pub fn check(file: &Source, workspace: &Workspace) -> Vec<Finding> {
    let _span = crate::profile::span("local_rules");
    let mut out = Vec::new();
    let inner = file.has_layer(&["core", "port"]);
    let deterministic = file.deterministic(workspace);
    for node in walk(&file.tree) {
        if ["Name", "Attribute"].contains(&kind(node)) && kind(child(node, "ctx")) == "Load" {
            let ns = names(file, node);
            if ns.is_empty() {
                continue;
            }
            let text = joined(&ns);
            if (inner
                || deterministic
                || (!file.layer().is_empty()
                    && !file.has_layer(&["test"])
                    && !file
                        .module
                        .as_ref()
                        .is_some_and(|m| workspace.policy.clock_modules.contains(m))))
                && ns.iter().all(|n| {
                    if inner || deterministic {
                        effects::nondeterministic(n)
                    } else {
                        effects::WALL_CLOCK.contains(&n.as_str())
                    }
                })
            {
                let msg = if deterministic {
                    format!(
                        "{text} hides nondeterminism; {} modules must be deterministic",
                        file.layer_name()
                    )
                } else if inner {
                    format!(
                        "{text} hides nondeterminism; pass the observed time, ID, or random value into the core"
                    )
                } else {
                    format!(
                        "{text} reads wall time directly; use the clock listed in workspace.clock_modules"
                    )
                };
                out.push(finding(file, node, "LIT201", msg, Some(text.clone())));
            }
            if inner && ns.iter().all(|n| effects::io(n)) {
                out.push(finding(
                    file,
                    node,
                    "LIT202",
                    format!("{text} performs I/O; pass its result into the core"),
                    Some(text.clone()),
                ));
            }
            if !file.layer().is_empty()
                && !file.has_layer(&["boundary", "transaction", "test"])
                && ns.iter().all(|n| effects::environment(n))
            {
                add(
                    &mut out,
                    file,
                    node,
                    "LIT301",
                    format!(
                        "{} modules cannot read the environment; read configuration at a boundary and pass it in",
                        file.layer_name()
                    ),
                );
            }
        }
        if kind(node) == "Call"
            && let Some(forbidden) = workspace.policy.forbidden_calls.get(file.layer_name())
        {
            let ns = names(file, child(node, "func"));
            let matched = ns
                .into_iter()
                .filter(|n| crate::workspace::matches_name(n, forbidden))
                .collect::<BTreeSet<_>>();
            if !matched.is_empty() {
                let text = joined(&matched);
                out.push(finding(
                    file,
                    node,
                    "LIT306",
                    format!("{} modules cannot call {text}", file.layer_name()),
                    Some(text),
                ));
            }
        }
    }
    {
        let _span = crate::profile::span("rule_simple");
        simple::check(file, workspace, &mut out);
    }
    {
        let _span = crate::profile::span("rule_defaults");
        defaults::check(file, &mut out);
    }
    {
        let _span = crate::profile::span("rule_ambient");
        ambient::check(file, &mut out);
    }
    {
        let _span = crate::profile::span("rule_mutation");
        mutation::check(file, &mut out);
    }
    {
        let _span = crate::profile::span("rule_capabilities");
        capabilities::check(file, workspace, &mut out);
    }
    {
        let _span = crate::profile::span("rule_subclass");
        subclass::check(file, workspace, &mut out);
    }
    out
}
