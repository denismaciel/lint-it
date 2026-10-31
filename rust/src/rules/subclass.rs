use super::*;
const DECLARATIVE: &[&str] = &[
    "sqlalchemy.ext.declarative.declarative_base",
    "sqlalchemy.orm.DeclarativeBase",
    "sqlalchemy.orm.DeclarativeBaseNoMeta",
    "sqlalchemy.orm.declarative_base",
];
fn all_in(ns: &BTreeSet<String>, allowed: &BTreeSet<String>) -> bool {
    !ns.is_empty()
        && !ns.contains("?")
        && ns.iter().all(|n| {
            allowed.contains(n)
                || allowed
                    .iter()
                    .any(|p| p.ends_with(".*") && n.starts_with(&p[..p.len() - 1]))
        })
}
fn definition<'a>(
    name: &str,
    w: &'a Workspace,
    seen: &mut HashSet<String>,
) -> Option<(&'a Node, &'a Source)> {
    if !seen.insert(name.into()) {
        return None;
    }
    let (module, attribute) = name.rsplit_once('.')?;
    let source = w.module_source(module)?;
    for st in items(&source.tree, "body") {
        if kind(st) == "ClassDef" && s(st, "name") == attribute {
            return Some((st, source));
        }
        if kind(st) == "Assign"
            && items(st, "targets")
                .iter()
                .any(|t| kind(t) == "Name" && s(t, "id") == attribute)
            || kind(st) == "AnnAssign"
                && kind(child(st, "target")) == "Name"
                && s(child(st, "target"), "id") == attribute
        {
            let value = child(st, "value");
            if !value.is_null() {
                return Some((value, source));
            }
        }
        if kind(st) == "ImportFrom"
            && let Some(imported) = symbols::absolute_module(st, source.package.as_deref())
        {
            for a in items(st, "names") {
                let local = if s(a, "asname").is_empty() {
                    s(a, "name")
                } else {
                    s(a, "asname")
                };
                if local == attribute {
                    return definition(&format!("{imported}.{}", s(a, "name")), w, seen);
                }
            }
        }
    }
    None
}
fn bases<'a>(
    base: &Node,
    scope: &'a Source,
    w: &'a Workspace,
) -> Option<Vec<(&'a Node, &'a Source)>> {
    let ns = names(scope, base);
    if ns == BTreeSet::from(["?".into()]) {
        let target = if kind(base) == "Subscript" {
            child(base, "value")
        } else {
            base
        };
        return items(&scope.tree, "body")
            .iter()
            .find(|n| {
                kind(target) == "Name" && kind(n) == "ClassDef" && s(n, "name") == s(target, "id")
            })
            .map(|n| vec![(n, scope)]);
    }
    ns.iter()
        .map(|n| definition(n, w, &mut HashSet::new()))
        .collect()
}
fn extendable(n: &Node, scope: &Source, allowed: &BTreeSet<String>) -> bool {
    if kind(n) != "ClassDef" {
        return all_in(&names(scope, n), allowed);
    }
    let ns = items(n, "bases")
        .iter()
        .map(|n| names(scope, n))
        .collect::<Vec<_>>();
    ns.iter()
        .any(|n| *n != BTreeSet::from(["builtins.object".into()]))
        && ns.iter().all(|n| all_in(n, allowed))
}
fn declarative(n: &Node, scope: &Source) -> bool {
    let allowed = DECLARATIVE.iter().map(|s| s.to_string()).collect();
    if kind(n) == "ClassDef" {
        items(n, "bases")
            .iter()
            .any(|b| all_in(&names(scope, b), &allowed))
    } else {
        all_in(&names(scope, n), &allowed)
    }
}
fn plain(n: &Node, scope: &Source) -> bool {
    kind(n) == "ClassDef"
        && items(n, "bases")
            .iter()
            .all(|b| names(scope, b) == BTreeSet::from(["builtins.object".into()]))
}
fn exception(n: &Node, scope: &Source, w: &Workspace, seen: &mut HashSet<(String, usize)>) -> bool {
    if kind(n) != "ClassDef" || !seen.insert((scope.filename.clone(), ast::id(n))) {
        return false;
    }
    for b in items(n, "bases") {
        let ns = names(scope, b);
        if !ns.is_empty() && ns.iter().all(|n| BUILTIN_EXCEPTIONS.contains(&n.as_str())) {
            return true;
        }
        if let Some(ds) = bases(b, scope, w)
            && ds
                .into_iter()
                .any(|(n, s)| exception(n, s, w, &mut seen.clone()))
        {
            return true;
        }
    }
    false
}
pub(super) fn check(file: &Source, w: &Workspace, out: &mut Vec<Finding>) {
    if file.layer().is_empty() {
        return;
    }
    let allowed = &w.policy.allowed_bases;
    let declarative_names = DECLARATIVE.iter().map(|n| n.to_string()).collect();
    for n in walk(&file.tree) {
        if kind(n) != "ClassDef" {
            continue;
        }
        let mut rejected = vec![];
        let mut mixins = vec![];
        let mut is_declarative = false;
        for base in items(n, "bases") {
            let ns = names(file, base);
            if all_in(&ns, &declarative_names) {
                is_declarative = true
            }
            if all_in(&ns, allowed) {
                continue;
            }
            let unknown = ns == BTreeSet::from(["?".into()]);
            let local = defaults::unparse(base);
            let mut described = if unknown {
                format!("'{local}', a workspace class")
            } else {
                joined(&ns)
            };
            let ds = bases(base, file, w);
            if ds.is_none()
                || ds.as_ref().is_some_and(|ds| {
                    ds.iter().any(|(d, scope)| {
                        scope.filename == file.filename && ast::id(d) == ast::id(n)
                    })
                })
            {
                if unknown {
                    described = format!("'{local}', which lint-it cannot resolve")
                }
                rejected.push((base, described));
                continue;
            }
            let ds = ds.unwrap();
            if ds.iter().all(|(d, s)| declarative(d, s)) {
                is_declarative = true
            }
            if ds
                .iter()
                .all(|(d, s)| extendable(d, s, allowed) || exception(d, s, w, &mut HashSet::new()))
            {
                continue;
            }
            if ds.iter().all(|(d, s)| plain(d, s)) {
                mixins.push((base, described))
            } else {
                rejected.push((base, described))
            }
        }
        if !is_declarative {
            rejected.extend(mixins)
        }
        for (base, description) in rejected {
            let ns = names(file, base);
            let local = defaults::unparse(base);
            let target = if ns != BTreeSet::from(["?".into()]) {
                joined(&ns)
            } else if let Some(module) = &file.module {
                format!("{module}.{local}")
            } else {
                local
            };
            out.push(finding(file,base,"LIT403",format!("'{}' extends {description}, which is not an allowed base; compose, or implement a Protocol (extend conventions.allowed_bases for framework bases)",s(n,"name")),Some(target)));
        }
    }
}
const BUILTIN_EXCEPTIONS: &[&str] = &[
    "builtins.ArithmeticError",
    "builtins.AssertionError",
    "builtins.AttributeError",
    "builtins.BaseException",
    "builtins.BaseExceptionGroup",
    "builtins.BlockingIOError",
    "builtins.BrokenPipeError",
    "builtins.BufferError",
    "builtins.BytesWarning",
    "builtins.ChildProcessError",
    "builtins.ConnectionAbortedError",
    "builtins.ConnectionError",
    "builtins.ConnectionRefusedError",
    "builtins.ConnectionResetError",
    "builtins.DeprecationWarning",
    "builtins.EOFError",
    "builtins.EncodingWarning",
    "builtins.EnvironmentError",
    "builtins.Exception",
    "builtins.ExceptionGroup",
    "builtins.FileExistsError",
    "builtins.FileNotFoundError",
    "builtins.FloatingPointError",
    "builtins.FutureWarning",
    "builtins.GeneratorExit",
    "builtins.IOError",
    "builtins.ImportError",
    "builtins.ImportWarning",
    "builtins.IndentationError",
    "builtins.IndexError",
    "builtins.InterruptedError",
    "builtins.IsADirectoryError",
    "builtins.KeyError",
    "builtins.KeyboardInterrupt",
    "builtins.LookupError",
    "builtins.MemoryError",
    "builtins.ModuleNotFoundError",
    "builtins.NameError",
    "builtins.NotADirectoryError",
    "builtins.NotImplementedError",
    "builtins.OSError",
    "builtins.OverflowError",
    "builtins.PendingDeprecationWarning",
    "builtins.PermissionError",
    "builtins.ProcessLookupError",
    "builtins.PythonFinalizationError",
    "builtins.RecursionError",
    "builtins.ReferenceError",
    "builtins.ResourceWarning",
    "builtins.RuntimeError",
    "builtins.RuntimeWarning",
    "builtins.StopAsyncIteration",
    "builtins.StopIteration",
    "builtins.SyntaxError",
    "builtins.SyntaxWarning",
    "builtins.SystemError",
    "builtins.SystemExit",
    "builtins.TabError",
    "builtins.TimeoutError",
    "builtins.TypeError",
    "builtins.UnboundLocalError",
    "builtins.UnicodeDecodeError",
    "builtins.UnicodeEncodeError",
    "builtins.UnicodeError",
    "builtins.UnicodeTranslateError",
    "builtins.UnicodeWarning",
    "builtins.UserWarning",
    "builtins.ValueError",
    "builtins.Warning",
    "builtins.ZeroDivisionError",
    "builtins._IncompleteInputError",
];
