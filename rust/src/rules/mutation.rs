use super::*;
#[derive(Clone, Default, PartialEq, Eq)]
struct Origin {
    borrowed: Option<String>,
    members: Option<String>,
    kind: Option<String>,
}
fn mutators(k: &str) -> &'static [&'static str] {
    match k {
        "builtins.list" => &[
            "append", "extend", "insert", "remove", "pop", "clear", "sort", "reverse",
        ],
        "builtins.dict" => &["clear", "pop", "popitem", "setdefault", "update"],
        "builtins.set" => &[
            "add",
            "clear",
            "discard",
            "pop",
            "remove",
            "update",
            "difference_update",
            "intersection_update",
            "symmetric_difference_update",
        ],
        _ => &[],
    }
}
struct Visitor<'a> {
    file: &'a Source,
    aliases: HashMap<String, Origin>,
    out: Vec<Finding>,
}
impl Visitor<'_> {
    fn origin(&self, n: &Node) -> Origin {
        match kind(n) {
            "Name" => self.aliases.get(s(n, "id")).cloned().unwrap_or_default(),
            "Attribute" | "Subscript" => {
                let b = self.origin(child(n, "value"));
                let root = b.borrowed.or(b.members);
                if kind(n) == "Subscript" && kind(child(n, "slice")) == "Slice" {
                    Origin {
                        members: root,
                        kind: b.kind,
                        ..Origin::default()
                    }
                } else {
                    Origin {
                        borrowed: root,
                        ..Origin::default()
                    }
                }
            }
            "List" | "Dict" | "Set" => {
                let roots = items(n, if kind(n) == "Dict" { "values" } else { "elts" })
                    .iter()
                    .filter_map(|v| self.origin(v).borrowed)
                    .collect::<BTreeSet<_>>();
                Origin {
                    members: if roots.len() == 1 {
                        roots.first().cloned()
                    } else {
                        None
                    },
                    kind: Some(format!("builtins.{}", kind(n).to_lowercase())),
                    ..Origin::default()
                }
            }
            "Call" => {
                let f = child(n, "func");
                let ns = names(self.file, f);
                if ns.len() == 1 && ns.first().is_some_and(|s| !mutators(s).is_empty()) {
                    let source = items(n, "args")
                        .first()
                        .map(|n| self.origin(n))
                        .unwrap_or_default();
                    Origin {
                        members: source.borrowed.or(source.members),
                        kind: ns.first().cloned(),
                        ..Origin::default()
                    }
                } else if kind(f) == "Attribute" && s(f, "attr") == "copy" {
                    let source = self.origin(child(f, "value"));
                    if source
                        .kind
                        .as_deref()
                        .is_some_and(|k| !mutators(k).is_empty())
                    {
                        Origin {
                            members: source.borrowed.or(source.members),
                            kind: source.kind,
                            ..Origin::default()
                        }
                    } else {
                        Origin::default()
                    }
                } else {
                    Origin::default()
                }
            }
            _ => Origin::default(),
        }
    }
    fn report(&mut self, n: &Node, o: Origin) {
        if let Some(b) = o.borrowed {
            add(
                &mut self.out,
                self.file,
                n,
                "LIT204",
                format!("mutation of caller-owned '{b}'; build and return a new value"),
            );
        }
    }
    fn write(&mut self, n: &Node) {
        match kind(n) {
            "Attribute" | "Subscript" => self.report(n, self.origin(child(n, "value"))),
            "Tuple" | "List" => {
                for e in items(n, "elts") {
                    self.write(e)
                }
            }
            _ => (),
        }
    }
    fn bind(&mut self, n: &Node, o: Origin) {
        for part in walk(n) {
            if kind(part) == "Name" && kind(child(part, "ctx")) == "Store" {
                self.aliases.insert(
                    s(part, "id").into(),
                    if kind(n) == "Name" {
                        o.clone()
                    } else {
                        Origin {
                            borrowed: o.borrowed.clone().or(o.members.clone()),
                            ..Origin::default()
                        }
                    },
                );
            }
        }
    }
    fn body(&mut self, b: &[Node]) {
        for n in b {
            self.visit(n)
        }
    }
    fn branches(&mut self, branches: Vec<Vec<&Node>>) {
        let mut exits = Vec::new();
        for body in branches {
            let mut v = Visitor {
                file: self.file,
                aliases: self.aliases.clone(),
                out: vec![],
            };
            for n in body {
                v.visit(n)
            }
            self.out.extend(v.out);
            exits.push(v.aliases);
        }
        let keys = exits
            .iter()
            .flat_map(|b| b.keys().cloned())
            .collect::<HashSet<_>>();
        for name in keys {
            let vals = exits
                .iter()
                .map(|b| b.get(&name).cloned().unwrap_or_default())
                .collect::<Vec<_>>();
            self.aliases.insert(
                name,
                if vals.iter().all(|v| v == &vals[0]) {
                    vals[0].clone()
                } else {
                    Origin::default()
                },
            );
        }
    }
    fn visit(&mut self, n: &Node) {
        match kind(n) {
            "FunctionDef" | "AsyncFunctionDef" | "ClassDef" | "Lambda" => (),
            "Assign" => {
                self.visit(child(n, "value"));
                let o = self.origin(child(n, "value"));
                for t in items(n, "targets") {
                    self.write(t);
                    self.bind(t, o.clone());
                }
            }
            "AnnAssign" => {
                if !child(n, "value").is_null() {
                    self.visit(child(n, "value"));
                    let t = child(n, "target");
                    self.write(t);
                    self.bind(t, self.origin(child(n, "value")));
                }
            }
            "NamedExpr" => {
                self.visit(child(n, "value"));
                self.bind(child(n, "target"), self.origin(child(n, "value")));
            }
            "AugAssign" => {
                self.visit(child(n, "value"));
                let t = child(n, "target");
                if kind(t) == "Name" {
                    let o = self.origin(t);
                    if o.kind.as_deref().is_some_and(|k| !mutators(k).is_empty()) {
                        self.report(n, o);
                    }
                } else {
                    self.write(t)
                }
            }
            "Delete" => {
                for t in items(n, "targets") {
                    self.write(t);
                    self.bind(t, Origin::default());
                }
            }
            "Call" => {
                let f = child(n, "func");
                if kind(f) == "Attribute" {
                    let o = self.origin(child(f, "value"));
                    if mutators(o.kind.as_deref().unwrap_or("")).contains(&s(f, "attr")) {
                        self.report(n, o);
                    }
                }
                let ns = names(self.file, f);
                if ns.len() == 1
                    && ns.iter().all(|n| {
                        [
                            "builtins.setattr",
                            "builtins.delattr",
                            "builtins.object.__setattr__",
                        ]
                        .contains(&n.as_str())
                    })
                    && let Some(a) = items(n, "args").first()
                {
                    self.report(n, self.origin(a));
                }
                for c in children(n) {
                    self.visit(c)
                }
            }
            "For" => {
                self.visit(child(n, "iter"));
                let o = self.origin(child(n, "iter"));
                self.bind(
                    child(n, "target"),
                    Origin {
                        borrowed: o.borrowed.or(o.members),
                        ..Origin::default()
                    },
                );
                self.branches(vec![vec![], items(n, "body").iter().collect()]);
                self.body(items(n, "orelse"));
            }
            "If" => {
                self.visit(child(n, "test"));
                self.branches(vec![
                    items(n, "body").iter().collect(),
                    items(n, "orelse").iter().collect(),
                ]);
            }
            "While" => {
                self.visit(child(n, "test"));
                self.branches(vec![vec![], items(n, "body").iter().collect()]);
                self.body(items(n, "orelse"));
            }
            "Try" => {
                let mut branches =
                    vec![items(n, "body").iter().chain(items(n, "orelse")).collect()];
                branches.extend(
                    items(n, "handlers")
                        .iter()
                        .map(|h| items(h, "body").iter().collect()),
                );
                self.branches(branches);
                self.body(items(n, "finalbody"));
            }
            "ListComp" | "SetComp" | "DictComp" | "GeneratorExp" => {
                let mut v = Visitor {
                    file: self.file,
                    aliases: self.aliases.clone(),
                    out: vec![],
                };
                for g in items(n, "generators") {
                    v.visit(child(g, "iter"));
                    let o = v.origin(child(g, "iter"));
                    v.bind(
                        child(g, "target"),
                        Origin {
                            borrowed: o.borrowed.or(o.members),
                            ..Origin::default()
                        },
                    );
                    v.body(items(g, "ifs"));
                }
                if kind(n) == "DictComp" {
                    v.visit(child(n, "key"));
                    v.visit(child(n, "value"));
                } else {
                    v.visit(child(n, "elt"));
                }
                self.out.extend(v.out);
            }
            _ => {
                for c in children(n) {
                    self.visit(c)
                }
            }
        }
    }
}
pub(super) fn check(file: &Source, out: &mut Vec<Finding>) {
    if !file.has_layer(&["core", "port"]) {
        return;
    }
    for n in walk(&file.tree) {
        if !["FunctionDef", "AsyncFunctionDef"].contains(&kind(n)) {
            continue;
        }
        let aliases = parameters(n)
            .into_iter()
            .filter(|a| !["self", "cls"].contains(&s(a, "arg")))
            .map(|a| {
                let ns = names(file, child(a, "annotation"));
                let k = if ns.len() == 1 {
                    ns.first().map(|n| match n.as_str() {
                        "typing.List"
                        | "typing.MutableSequence"
                        | "collections.abc.MutableSequence" => "builtins.list".into(),
                        "typing.Dict"
                        | "typing.MutableMapping"
                        | "collections.abc.MutableMapping" => "builtins.dict".into(),
                        "typing.Set" | "typing.MutableSet" | "collections.abc.MutableSet" => {
                            "builtins.set".into()
                        }
                        _ => n.clone(),
                    })
                } else {
                    None
                };
                (
                    s(a, "arg").into(),
                    Origin {
                        borrowed: Some(s(a, "arg").into()),
                        kind: k,
                        ..Origin::default()
                    },
                )
            })
            .collect();
        let mut v = Visitor {
            file,
            aliases,
            out: vec![],
        };
        v.body(items(n, "body"));
        out.extend(v.out);
    }
}
