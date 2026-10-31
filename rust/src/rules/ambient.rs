use super::*;
fn scope(n: &Node) -> Vec<&Node> {
    let mut result = vec![n];
    if !["FunctionDef", "AsyncFunctionDef", "ClassDef", "Lambda"].contains(&kind(n)) {
        for c in children(n) {
            result.extend(scope(c));
        }
    }
    result
}
fn locals(body: &[Node]) -> HashSet<String> {
    fn collect(n: &Node, result: &mut HashSet<String>) {
        match kind(n) {
            "Name" if kind(child(n, "ctx")) == "Store" => {
                result.insert(s(n, "id").into());
            }
            "FunctionDef" | "AsyncFunctionDef" | "ClassDef" => {
                result.insert(s(n, "name").into());
                return;
            }
            "Lambda" | "ListComp" | "SetComp" | "DictComp" | "GeneratorExp" => return,
            "Import" | "ImportFrom" => {
                for a in items(n, "names") {
                    let name = if !s(a, "asname").is_empty() {
                        s(a, "asname")
                    } else if kind(n) == "Import" {
                        s(a, "name").split('.').next().unwrap_or("")
                    } else {
                        s(a, "name")
                    };
                    result.insert(name.into());
                }
                return;
            }
            _ => (),
        }
        for c in children(n) {
            collect(c, result)
        }
    }
    let mut result = HashSet::new();
    for n in body {
        collect(n, &mut result)
    }
    result
}
pub(super) fn check(file: &Source, out: &mut Vec<Finding>) {
    if !file.has_layer(&["core", "port"]) {
        return;
    }
    let nodes = walk(&file.tree);
    let parents = nodes
        .iter()
        .flat_map(|n| children(n).into_iter().map(move |c| (ast::id(c), *n)))
        .collect::<HashMap<_, _>>();
    let mut globals = HashSet::new();
    for st in items(&file.tree, "body") {
        if !["Assign", "AnnAssign"].contains(&kind(st)) {
            continue;
        }
        let v = child(st, "value");
        let ns = names(file, child(v, "func"));
        if ["List", "Dict", "Set", "ListComp", "DictComp", "SetComp"].contains(&kind(v))
            || kind(v) == "Call"
                && ns.len() == 1
                && ns.iter().all(|n| {
                    ["builtins.list", "builtins.dict", "builtins.set"].contains(&n.as_str())
                })
        {
            let targets = if kind(st) == "Assign" {
                items(st, "targets").iter().collect()
            } else {
                vec![child(st, "target")]
            };
            for t in targets {
                if kind(t) == "Name" {
                    globals.insert(s(t, "id").to_owned());
                }
            }
        }
    }
    for n in nodes {
        if ["Name", "Attribute"].contains(&kind(n)) && kind(child(n, "ctx")) == "Load" {
            let ns = names(file, n);
            if !ns.is_empty() && ns.iter().all(|n| effects::ambient(n)) {
                let text = joined(&ns);
                out.push(finding(
                    file,
                    n,
                    "LIT203",
                    format!(
                        "{text} uses ambient state; pass an explicit value or policy into the core"
                    ),
                    Some(text),
                ));
            }
        }
        if !["FunctionDef", "AsyncFunctionDef"].contains(&kind(n)) {
            continue;
        }
        let localnodes = items(n, "body").iter().flat_map(scope).collect::<Vec<_>>();
        let external = localnodes
            .iter()
            .filter(|n| ["Global", "Nonlocal"].contains(&kind(n)))
            .flat_map(|n| items(n, "names"))
            .filter_map(Node::as_str)
            .collect::<HashSet<_>>();
        let mut shadowed = locals(items(n, "body"));
        for a in parameters(n).into_iter().chain([
            child(child(n, "args"), "vararg"),
            child(child(n, "args"), "kwarg"),
        ]) {
            shadowed.insert(s(a, "arg").into());
        }
        let mut parent = parents.get(&ast::id(n));
        while let Some(p) = parent {
            if ["FunctionDef", "AsyncFunctionDef", "Lambda"].contains(&kind(p)) {
                shadowed.extend(parameters(p).iter().map(|a| s(a, "arg").to_owned()));
                if kind(p) != "Lambda" {
                    shadowed.extend(locals(items(p, "body")));
                }
            }
            parent = parents.get(&ast::id(p));
        }
        shadowed.retain(|s| !external.contains(s.as_str()));
        for c in localnodes {
            if kind(c) != "Name" {
                continue;
            }
            let name = s(c, "id");
            let ctx = kind(child(c, "ctx"));
            if ["Store", "Del"].contains(&ctx) && external.contains(name) {
                add(
                    out,
                    file,
                    c,
                    "LIT203",
                    format!("write to global/nonlocal '{name}'; return the updated state instead"),
                );
            } else if ctx == "Load" && globals.contains(name) && !shadowed.contains(name) {
                add(
                    out,
                    file,
                    c,
                    "LIT203",
                    format!(
                        "mutable module state '{name}'; use an immutable constant or pass a snapshot"
                    ),
                );
            }
        }
    }
}
