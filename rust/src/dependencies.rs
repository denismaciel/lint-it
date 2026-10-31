use crate::{
    ast::{self, Node, items, kind, s},
    model::{Finding, Source, finding},
    symbols,
    workspace::Workspace,
};
use std::collections::{BTreeSet, HashSet};
fn edges<'a>(
    nodes: impl IntoIterator<Item = &'a Node>,
    package: Option<&str>,
) -> Vec<(&'a Node, String, Option<String>)> {
    let mut out = vec![];
    for n in nodes {
        if kind(n) == "Import" {
            for a in items(n, "names") {
                out.push((n, s(a, "name").into(), None));
            }
        } else if kind(n) == "ImportFrom"
            && let Some(base) = symbols::absolute_module(n, package)
        {
            for a in items(n, "names") {
                out.push((n, base.clone(), Some(s(a, "name").into())));
            }
        }
    }
    out
}
fn targets<'a>(
    module: &str,
    name: Option<&str>,
    ws: &'a Workspace,
    seen: &mut HashSet<(String, Option<String>)>,
) -> Vec<&'a Source> {
    if !seen.insert((module.into(), name.map(str::to_owned))) {
        return vec![];
    }
    if let Some(n) = name
        && let Some(f) = ws.module_source(&format!("{module}.{n}"))
    {
        return vec![f];
    }
    let Some(f) = ws.module_source(module) else {
        return vec![];
    };
    if let Some(name) = name {
        let mut exports = vec![];
        for (n, m, sym) in ws.top_imports(f) {
            if kind(n) == "ImportFrom"
                && items(n, "names").iter().any(|a| {
                    s(a, "name") == sym.as_deref().unwrap_or("")
                        && (alias(a) == name || name == "*" || s(a, "name") == "*")
                })
            {
                exports.extend(targets(m, sym.as_deref(), ws, seen));
            }
        }
        if !exports.is_empty() {
            return exports;
        }
    }
    vec![f]
}
fn alias(n: &Node) -> &str {
    if s(n, "asname").is_empty() {
        s(n, "name")
    } else {
        s(n, "asname")
    }
}
fn loaded<'a>(module: &str, name: Option<&str>, ws: &'a Workspace) -> Vec<&'a Source> {
    let mut pending = vec![(module.to_string(), name.map(str::to_owned), false)];
    let mut seen = HashSet::new();
    let mut expanded = HashSet::new();
    let mut emitted = HashSet::new();
    let mut result = vec![];
    while let Some((m, n, transitive)) = pending.pop() {
        if !seen.insert((m.clone(), n.clone(), transitive)) {
            continue;
        }
        let targets = targets(&m, n.as_deref(), ws, &mut HashSet::new());
        let mut names = vec![m];
        names.extend(targets.iter().filter_map(|f| f.module.clone()));
        let mut loaded = targets;
        for name in names {
            let parts: Vec<_> = name.split('.').collect();
            for len in 1..=parts.len() {
                if let Some(f) = ws.module_source(&parts[..len].join("."))
                    && (len == parts.len() || marker(f))
                    && !loaded.iter().any(|x| x.path == f.path)
                {
                    loaded.push(f)
                }
            }
        }
        for f in loaded {
            if emitted.insert(&f.path) {
                result.push(f);
            }
            if !expanded.contains(&f.path) && (marker(f) || transitive) {
                expanded.insert(&f.path);
                pending.extend(
                    ws.initialization_imports(f)
                        .iter()
                        .map(|(m, n)| (m.clone(), n.clone(), true)),
                );
            }
        }
    }
    result
}
fn marker(f: &Source) -> bool {
    f.path.file_name().is_some_and(|s| s == "__init__.py")
}
fn reexported(
    module: &str,
    symbol: Option<&str>,
    ws: &Workspace,
    forbidden: &BTreeSet<String>,
    seen: &mut HashSet<(String, Option<String>)>,
) -> BTreeSet<String> {
    if !seen.insert((module.into(), symbol.map(str::to_owned))) {
        return BTreeSet::new();
    }
    let root = module.split('.').next().unwrap_or("");
    if forbidden.contains(root) {
        return BTreeSet::from([root.into()]);
    }
    let (Some(f), Some(symbol)) = (ws.module_source(module), symbol) else {
        return BTreeSet::new();
    };
    let mut reached = BTreeSet::new();
    for (n, m, member) in ws.top_imports(f) {
        let exported = items(n, "names").iter().any(|a| {
            if kind(n) == "ImportFrom" {
                s(a, "name") == member.as_deref().unwrap_or("")
                    && (alias(a) == symbol || symbol == "*" || s(a, "name") == "*")
            } else {
                s(a, "name") == m.as_str()
                    && (if s(a, "asname").is_empty() {
                        s(a, "name").split('.').next().unwrap_or("")
                    } else {
                        s(a, "asname")
                    }) == symbol
            }
        });
        if exported {
            reached.extend(reexported(m, member.as_deref(), ws, forbidden, seen));
        }
    }
    reached
}
fn domain(module: &str) -> Option<(&str, &str)> {
    let p: Vec<_> = module.split('.').collect();
    if p.len() > 2 && p[1] == "domains" {
        Some((p[0], p[2]))
    } else {
        None
    }
}
pub fn check(file: &Source, ws: &Workspace) -> Vec<Finding> {
    let _span = crate::profile::span("dependencies");
    let mut out = vec![];
    if file.classification.is_none() {
        let mut message = "file matches no layer in its package layout".to_string();
        if let Some(i) = ws.owner(&file.path) {
            message += &format!(
                " ({}); move it, extend the layout, or add an override",
                ws.packages[i].layout
            );
        }
        out.push(finding(file, &file.tree, "LIT002", message, None));
    }
    let nodes = ast::walk(&file.tree);
    let imports = edges(nodes.iter().copied(), file.package.as_deref());
    let layer = file.layer_name();
    let allowed = ws.policy.layer_dependencies.get(layer);
    let check_layer = !layer.is_empty()
        && file.package.is_some()
        && !(allowed.is_none() && file.layer() == "test");
    let owner = file.module.as_deref().and_then(domain);
    let mut seen_layer = HashSet::new();
    let mut seen_domain = HashSet::new();
    for (node, m, n) in &imports {
        if check_layer || owner.is_some() {
            for target in ws.loaded_sources(m, n.as_deref(), || loaded(m, n.as_deref(), ws)) {
                let module = target.module.as_deref().unwrap_or("");
                let overridden = ws.dependency_overridden(file, target);
                if check_layer && let Some(c) = &target.classification {
                    let permitted =
                        allowed.map_or(c.layer != "test", |a| ws.policy.is_a(&c.name, a));
                    if target.path != file.path
                        && !seen_layer.contains(&target.path)
                        && !permitted
                        && c.layer != "marker"
                        && !ws.policy.allows_dependency(layer, module)
                        && !overridden
                    {
                        seen_layer.insert(&target.path);
                        out.push(finding(
                            file,
                            node,
                            "LIT101",
                            format!("{layer} cannot import {} module {module}", c.name),
                            Some(module.into()),
                        ));
                    }
                }
                if let (Some(owner), Some(to)) = (owner, domain(module)) {
                    if to.0 != owner.0
                        || to == owner
                        || seen_domain.contains(&target.path)
                        || target.layer() == "marker"
                        || overridden
                    {
                        continue;
                    }
                    let declared = ws
                        .policy
                        .domain_dependencies
                        .get(owner.1)
                        .is_some_and(|d| d.contains(to.1));
                    let message = if !declared {
                        Some(format!(
                            "{} domain cannot import {module}: {} is not in domains.{}",
                            owner.1, to.1, owner.1
                        ))
                    } else if !["core", "shell"].contains(&target.layer()) {
                        Some(format!(
                            "{} domain cannot import {module}: only the core and shell modules of {} are public",
                            owner.1, to.1
                        ))
                    } else {
                        None
                    };
                    if let Some(message) = message {
                        seen_domain.insert(&target.path);
                        out.push(finding(file, node, "LIT104", message, Some(module.into())));
                    }
                }
            }
        }
    }
    if let Some(forbidden) = ws
        .policy
        .forbidden_imports
        .get(layer)
        .filter(|f| !f.is_empty())
    {
        for node in &nodes {
            if !["Import", "ImportFrom"].contains(&kind(node)) {
                continue;
            }
            let mut reached = BTreeSet::new();
            for (_, m, n) in edges([*node], file.package.as_deref()) {
                reached.extend(reexported(
                    &m,
                    n.as_deref(),
                    ws,
                    forbidden,
                    &mut HashSet::new(),
                ));
            }
            if !reached.is_empty() {
                let target = reached.into_iter().collect::<Vec<_>>().join(", ");
                out.push(finding(
                    file,
                    node,
                    "LIT102",
                    format!("{layer} modules cannot import {target}"),
                    Some(target),
                ));
            }
        }
    }
    if ws
        .owner(&file.path)
        .is_some_and(|i| ws.packages[i].kind == "client")
    {
        let servers: BTreeSet<_> = ws
            .sources
            .iter()
            .filter(|f| {
                ws.owner(&f.path)
                    .is_some_and(|i| ws.packages[i].kind == "server")
                    && f.module
                        .as_deref()
                        .and_then(|m| ws.module_source(m))
                        .is_some_and(|winner| winner.path == f.path)
            })
            .filter_map(|f| f.module.as_deref().and_then(|m| m.split('.').next()))
            .collect();
        for node in nodes {
            let modules: Vec<&str> = match kind(node) {
                "Import" => items(node, "names").iter().map(|a| s(a, "name")).collect(),
                "ImportFrom" => {
                    if !node["module"].is_null() {
                        vec![s(node, "module")]
                    } else {
                        items(node, "names").iter().map(|a| s(a, "name")).collect()
                    }
                }
                _ => vec![],
            };
            for m in modules {
                if servers.contains(m.split('.').next().unwrap_or("")) {
                    out.push(finding(
                        file,
                        node,
                        "LIT103",
                        format!("client packages cannot import server module {m}"),
                        Some(m.into()),
                    ));
                }
            }
        }
    }
    out
}
