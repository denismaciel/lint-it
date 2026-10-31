use super::*;
const EFFECTFUL: &[&str] = &[
    "aiohttp.ClientSession",
    "aiohttp.client.ClientSession",
    "fsspec.AbstractFileSystem",
    "fsspec.spec.AbstractFileSystem",
    "httpx.AsyncClient",
    "httpx.Client",
    "io.BufferedIOBase",
    "io.IOBase",
    "io.RawIOBase",
    "io.TextIOBase",
    "io.TextIOWrapper",
    "psycopg.AsyncConnection",
    "psycopg.Connection",
    "requests.Session",
    "requests.sessions.Session",
    "sqlalchemy.engine.Connection",
    "sqlalchemy.engine.Engine",
    "sqlalchemy.ext.asyncio.AsyncSession",
    "sqlalchemy.ext.asyncio.session.AsyncSession",
    "sqlalchemy.orm.Session",
    "sqlalchemy.orm.session.Session",
    "sqlite3.Connection",
    "sqlite3.Cursor",
    "typing.BinaryIO",
    "typing.IO",
    "typing.TextIO",
];
fn normalize(n: &mut Node) {
    if kind(n) == "Constant"
        && let Some(text) = n["value"].as_str()
        && let Some(mut parsed) = ast::parse_expression(text)
        && kind(&parsed) != "Constant"
    {
        normalize(&mut parsed);
        for key in ["lineno", "col_offset"] {
            if let Some(v) = n.get(key) {
                parsed[key] = v.clone();
            }
        }
        *n = parsed;
        return;
    }
    if let Some(obj) = n.as_object_mut() {
        for (k, v) in obj {
            if k.starts_with('_') {
                continue;
            }
            if v.is_object() {
                normalize(v)
            } else if let Some(a) = v.as_array_mut() {
                for v in a {
                    normalize(v)
                }
            }
        }
    }
}
fn rewrite(n: &mut Node) {
    if kind(n) == "arg"
        && let Some(a) = n.get_mut("annotation")
    {
        normalize(a)
    }
    if let Some(obj) = n.as_object_mut() {
        for (k, v) in obj {
            if k.starts_with('_') {
                continue;
            }
            if v.is_object() {
                rewrite(v)
            } else if let Some(a) = v.as_array_mut() {
                for v in a {
                    rewrite(v)
                }
            }
        }
    }
}
fn reid(n: &mut Node, c: &mut usize) {
    if n.get("_type").is_some() {
        n["_id"] = serde_json::json!(*c);
        *c += 1;
    }
    if let Some(obj) = n.as_object_mut() {
        for (k, v) in obj {
            if k.starts_with('_') {
                continue;
            }
            if v.is_object() {
                reid(v, c)
            } else if let Some(a) = v.as_array_mut() {
                for v in a {
                    reid(v, c)
                }
            }
        }
    }
}
fn annotation_nodes<'a>(n: &'a Node, symbols: &symbols::Symbols) -> Vec<&'a Node> {
    let mut out = vec![n];
    if kind(n) == "Subscript" {
        let ns = symbols::names(symbols, child(n, "value"));
        if ns
            .iter()
            .any(|s| ["typing.Literal", "typing_extensions.Literal"].contains(&s.as_str()))
        {
            return out;
        }
        if ns
            .iter()
            .any(|s| ["typing.Annotated", "typing_extensions.Annotated"].contains(&s.as_str()))
        {
            let sl = child(n, "slice");
            let first = if kind(sl) == "Tuple" {
                items(sl, "elts").first().unwrap_or(sl)
            } else {
                sl
            };
            out.extend(annotation_nodes(first, symbols));
            return out;
        }
    }
    for c in children(n) {
        out.extend(annotation_nodes(c, symbols))
    }
    out
}
pub(super) fn check(file: &Source, w: &Workspace, out: &mut Vec<Finding>) {
    if !file.has_layer(&["core"]) {
        return;
    }
    let has_strings = walk(&file.tree)
        .into_iter()
        .filter(|n| kind(n) == "arg")
        .any(|a| {
            walk(child(a, "annotation"))
                .into_iter()
                .any(|n| kind(n) == "Constant" && n["value"].is_string())
        });
    let rewritten;
    let resolved;
    let (tree, syms) = if has_strings {
        let mut tree = file.tree.clone();
        rewrite(&mut tree);
        reid(&mut tree, &mut 1);
        resolved = symbols::resolve(&tree, file.package.as_deref());
        rewritten = tree;
        (&rewritten, &resolved)
    } else {
        (&file.tree, &file.symbols)
    };
    for a in walk(tree) {
        if kind(a) != "arg" || child(a, "annotation").is_null() {
            continue;
        }
        let mut matched = BTreeSet::new();
        for n in annotation_nodes(child(a, "annotation"), syms) {
            let ns = symbols::names(syms, n);
            if !ns.is_empty()
                && ns.iter().all(|s| {
                    EFFECTFUL.contains(&s.as_str()) || w.policy.effectful_types.contains(s)
                })
            {
                matched.extend(ns)
            }
        }
        if !matched.is_empty() {
            add(
                out,
                file,
                a,
                "LIT207",
                format!(
                    "core parameter '{}' receives effectful capability {}; pass observed values and execute returned decisions in the shell",
                    s(a, "arg"),
                    joined(&matched)
                ),
            );
        }
    }
}
