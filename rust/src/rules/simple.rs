use super::*;
pub(super) fn check(file: &Source, w: &Workspace, out: &mut Vec<Finding>) {
    let inner = file.has_layer(&["core", "port"]);
    let core = file.has_layer(&["core"]);
    for n in walk(&file.tree) {
        let k = kind(n);
        let f = child(n, "func");
        if core && ["Await", "AsyncFor", "AsyncWith"].contains(&k) {
            add(
                out,
                file,
                n,
                "LIT206",
                "async execution belongs in the shell; the core computes decisions from values",
            );
        }
        if core && ["Name", "Attribute"].contains(&k) && kind(child(n, "ctx")) == "Load" {
            let ns = names(file, n);
            if !ns.is_empty() && ns.iter().all(|n| effects::asynchronous(n)) {
                add(
                    out,
                    file,
                    n,
                    "LIT206",
                    "task and thread scheduling belongs in the shell",
                );
            }
        }
        if !file.layer().is_empty()
            && !file.has_layer(&["transaction", "test"])
            && k == "Call"
            && kind(f) == "Attribute"
            && ["commit", "rollback"].contains(&s(f, "attr"))
        {
            add(
                out,
                file,
                n,
                "LIT302",
                format!(
                    "{}() is only allowed at transaction boundaries",
                    s(f, "attr")
                ),
            );
        }
        if file.has_layer(&["router"]) && k == "Call" {
            let ns = names(file, f);
            let mut short = ns
                .iter()
                .map(|n| n.rsplit('.').next().unwrap_or(n).to_owned())
                .collect::<BTreeSet<_>>();
            if short.is_empty() || ns == BTreeSet::from(["?".into()]) {
                short.clear();
                let v = if kind(f) == "Name" {
                    s(f, "id")
                } else if kind(f) == "Attribute" {
                    s(f, "attr")
                } else {
                    ""
                };
                if !v.is_empty() {
                    short.insert(v.into());
                }
            }
            if !short.is_empty()
                && short.iter().all(|n| {
                    ["Repository", "Client", "Engine"]
                        .iter()
                        .any(|v| n.ends_with(v))
                        || ["create_async_engine", "create_engine", "load_settings"]
                            .contains(&n.as_str())
                })
            {
                let text = joined(&short);
                out.push(finding(
                    file,
                    n,
                    "LIT303",
                    format!("routers cannot construct {text}"),
                    Some(text),
                ));
            }
        }
        if file.has_layer(&["test"]) {
            if k == "Import"
                && items(n, "names").iter().any(|a| {
                    s(a, "name") == "unittest.mock" || s(a, "name").starts_with("unittest.mock.")
                })
                || k == "ImportFrom"
                    && (s(n, "module") == "unittest.mock"
                        || s(n, "module") == "unittest"
                            && items(n, "names").iter().any(|a| s(a, "name") == "mock"))
            {
                add(
                    out,
                    file,
                    n,
                    "LIT304",
                    "do not import unittest.mock in tests",
                );
            }
            if ["FunctionDef", "AsyncFunctionDef"].contains(&k) {
                for a in parameters(n) {
                    if ["mocker", "class_mocker", "module_mocker", "package_mocker"]
                        .contains(&s(a, "arg"))
                    {
                        add(
                            out,
                            file,
                            a,
                            "LIT304",
                            "do not use pytest-mock fixtures in tests",
                        );
                    }
                }
            }
            if k == "Call"
                && kind(f) == "Attribute"
                && kind(child(f, "value")) == "Name"
                && s(child(f, "value"), "id") == "monkeypatch"
                && [
                    "chdir",
                    "context",
                    "delattr",
                    "delenv",
                    "delitem",
                    "setattr",
                    "setenv",
                    "setitem",
                    "syspath_prepend",
                ]
                .contains(&s(f, "attr"))
            {
                add(
                    out,
                    file,
                    n,
                    "LIT304",
                    "do not use pytest monkeypatch in tests",
                );
            }
        }
        if core
            && ["FunctionDef", "AsyncFunctionDef"].contains(&k)
            && !s(n, "name").starts_with('_')
        {
            for a in parameters(n) {
                if !["self", "cls"].contains(&s(a, "arg")) && has_bool(child(a, "annotation")) {
                    add(
                        out,
                        file,
                        a,
                        "LIT401",
                        format!(
                            "policy input '{}' is boolean; use a named enum or value type",
                            s(a, "arg")
                        ),
                    );
                }
            }
            if has_bool(child(n, "returns"))
                && !w
                    .policy
                    .predicate_prefixes
                    .iter()
                    .any(|p| s(n, "name").starts_with(p))
            {
                add(
                    out,
                    file,
                    n,
                    "LIT401",
                    format!(
                        "decision '{}' returns bool; return a named result or enum",
                        s(n, "name")
                    ),
                );
            }
        }
        if core && ["Raise", "ExceptHandler"].contains(&k) {
            let e = child(n, if k == "Raise" { "exc" } else { "type" });
            if exception_names(e)
                .iter()
                .any(|n| w.policy.outcome_suffixes.iter().any(|v| n.ends_with(v)))
            {
                add(
                    out,
                    file,
                    n,
                    "LIT402",
                    if k == "Raise" {
                        "expected outcomes must be returned as named results, not raised"
                    } else {
                        "expected outcomes must be matched as named results, not caught"
                    },
                );
            }
        }
        if inner && k == "ClassDef" {
            frozen(file, n, out);
        }
    }
}
fn has_bool(n: &Node) -> bool {
    match kind(n) {
        "Name" => s(n, "id") == "bool",
        "BinOp" if kind(child(n, "op")) == "BitOr" => {
            has_bool(child(n, "left")) || has_bool(child(n, "right"))
        }
        "Subscript" => {
            let v = child(n, "value");
            if ["Union", "Optional"].contains(&if kind(v) == "Name" {
                s(v, "id")
            } else {
                s(v, "attr")
            }) {
                let sl = child(n, "slice");
                if kind(sl) == "Tuple" {
                    items(sl, "elts").iter().any(has_bool)
                } else {
                    has_bool(sl)
                }
            } else {
                false
            }
        }
        _ => false,
    }
}
fn exception_names(n: &Node) -> Vec<&str> {
    match kind(n) {
        "Tuple" => items(n, "elts").iter().flat_map(exception_names).collect(),
        "Call" => exception_names(child(n, "func")),
        "Name" => vec![s(n, "id")],
        "Attribute" => vec![s(n, "attr")],
        _ => vec![],
    }
}
fn frozen(file: &Source, n: &Node, out: &mut Vec<Finding>) {
    let ds = items(n, "decorator_list")
        .iter()
        .filter(|d| {
            names(
                file,
                if kind(d) == "Call" {
                    child(d, "func")
                } else {
                    d
                },
            ) == BTreeSet::from(["dataclasses.dataclass".into()])
        })
        .collect::<Vec<_>>();
    if ds.is_empty() {
        return;
    }
    if !ds.iter().any(|d| {
        kind(d) == "Call"
            && items(d, "keywords").iter().any(|kw| {
                s(kw, "arg") == "frozen"
                    && kind(child(kw, "value")) == "Constant"
                    && child(kw, "value").get("value").and_then(Node::as_bool) == Some(true)
            })
    }) {
        add(
            out,
            file,
            n,
            "LIT205",
            "core dataclasses must be frozen; return a replacement value for transitions",
        );
    }
    for st in items(n, "body") {
        if kind(st) != "AnnAssign" {
            continue;
        }
        let a = child(st, "annotation");
        if kind(a) == "Subscript"
            && names(file, child(a, "value")) == BTreeSet::from(["typing.ClassVar".into()])
        {
            continue;
        }
        if walk(a).iter().any(|a| {
            names(file, a).iter().any(|v| {
                [
                    "builtins.list",
                    "builtins.dict",
                    "builtins.set",
                    "typing.List",
                    "typing.Dict",
                    "typing.Set",
                    "typing.MutableMapping",
                    "typing.MutableSequence",
                    "typing.MutableSet",
                    "collections.abc.MutableMapping",
                    "collections.abc.MutableSequence",
                    "collections.abc.MutableSet",
                ]
                .contains(&v.as_str())
            })
        }) {
            add(
                out,
                file,
                st,
                "LIT205",
                "frozen records must not expose mutable collection fields; use tuples, frozensets, or a read-only collection interface",
            );
        }
    }
}
