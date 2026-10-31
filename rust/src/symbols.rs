//! Conservative, flow-sensitive bindings matching the Python implementation.
use crate::ast::{self, Node, child, children, id, items, kind, s, walk};
use std::collections::{BTreeSet, HashMap};
pub type Symbols = HashMap<usize, BTreeSet<String>>;
type Bindings = HashMap<String, BTreeSet<String>>;
fn unknown() -> BTreeSet<String> {
    BTreeSet::from(["?".into()])
}
fn singleton(s: impl Into<String>) -> BTreeSet<String> {
    BTreeSet::from([s.into()])
}
pub fn names(symbols: &Symbols, node: &Node) -> BTreeSet<String> {
    symbols.get(&id(node)).cloned().unwrap_or_else(unknown)
}
pub fn absolute_module(node: &Node, package: Option<&str>) -> Option<String> {
    let level = child(node, "level").as_u64().unwrap_or(0) as usize;
    if level == 0 {
        return child(node, "module").as_str().map(str::to_string);
    }
    let package = package?;
    let parts: Vec<_> = if package.is_empty() {
        vec![]
    } else {
        package.split('.').collect()
    };
    if level > parts.len() {
        return None;
    }
    let mut prefix = parts[..parts.len() - level + 1].to_vec();
    if !s(node, "module").is_empty() {
        prefix.push(s(node, "module"));
    }
    Some(prefix.join("."))
}
fn stored_names(node: &Node) -> BTreeSet<String> {
    walk(node)
        .iter()
        .filter(|n| kind(n) == "Name" && kind(child(n, "ctx")) == "Store")
        .map(|n| s(n, "id").to_string())
        .collect()
}
fn locals(node: &Node, result: &mut BTreeSet<String>) {
    match kind(node) {
        "Name" => {
            if kind(child(node, "ctx")) == "Store" {
                result.insert(s(node, "id").into());
            }
        }
        "Import" | "ImportFrom" => {
            for alias in items(node, "names") {
                let name = s(alias, "name");
                result.insert(
                    if !s(alias, "asname").is_empty() {
                        s(alias, "asname")
                    } else if kind(node) == "Import" {
                        name.split('.').next().unwrap_or(name)
                    } else {
                        name
                    }
                    .into(),
                );
            }
        }
        "FunctionDef" | "AsyncFunctionDef" | "ClassDef" => {
            result.insert(s(node, "name").into());
        }
        "Lambda" | "ListComp" | "SetComp" | "DictComp" | "GeneratorExp" => {}
        _ => {
            for c in children(node) {
                locals(c, result)
            }
        }
    }
}
fn local_names(body: &[Node]) -> BTreeSet<String> {
    let mut result = BTreeSet::new();
    for node in body {
        locals(node, &mut result)
    }
    result
}
fn is_expr(node: &Node) -> bool {
    matches!(
        kind(node),
        "BoolOp"
            | "NamedExpr"
            | "BinOp"
            | "UnaryOp"
            | "Lambda"
            | "IfExp"
            | "Dict"
            | "Set"
            | "ListComp"
            | "SetComp"
            | "DictComp"
            | "GeneratorExp"
            | "Await"
            | "Yield"
            | "YieldFrom"
            | "Compare"
            | "Call"
            | "FormattedValue"
            | "JoinedStr"
            | "TemplateStr"
            | "Constant"
            | "Attribute"
            | "Subscript"
            | "Starred"
            | "Name"
            | "List"
            | "Tuple"
            | "Slice"
    )
}
struct Resolver<'a> {
    bindings: Bindings,
    references: Symbols,
    function_parent: Option<Bindings>,
    package: Option<&'a str>,
}
impl<'a> Resolver<'a> {
    fn new(bindings: Bindings, package: Option<&'a str>) -> Self {
        Self {
            bindings,
            references: HashMap::new(),
            function_parent: None,
            package,
        }
    }
    fn child(&self, bindings: Bindings) -> Self {
        Self::new(bindings, self.package)
    }
    fn names(&self, node: &Node) -> BTreeSet<String> {
        self.names_depth(node, 0)
    }
    fn names_depth(&self, node: &Node, depth: usize) -> BTreeSet<String> {
        if depth > 64 {
            return unknown();
        }
        match kind(node) {
            "Name" => self
                .bindings
                .get(s(node, "id"))
                .cloned()
                .unwrap_or_else(unknown),
            "Attribute" => self
                .names_depth(child(node, "value"), depth + 1)
                .into_iter()
                .map(|name| {
                    if name == "?" {
                        name
                    } else {
                        format!("{name}.{}", s(node, "attr"))
                    }
                })
                .collect(),
            "Call" => self
                .names_depth(child(node, "func"), depth + 1)
                .into_iter()
                .map(|name| match name.as_str() {
                    "logging.getLogger" => "logging.Logger".into(),
                    "structlog.get_logger" => "structlog.BoundLogger".into(),
                    "pathlib.Path.home" | "pathlib.Path.cwd" => "pathlib.Path".into(),
                    _ => name,
                })
                .collect(),
            "Subscript" => self.names_depth(child(node, "value"), depth + 1),
            "BinOp" if kind(child(node, "op")) == "Div" => {
                self.names_depth(child(node, "left"), depth + 1)
            }
            "Constant" => {
                if let Some(text) = child(node, "value").as_str()
                    && !text.contains('\n')
                    && text.chars().count() <= 200
                    && let Some(expr) = ast::parse_expression(text)
                {
                    return self.names_depth(&expr, depth + 1);
                }
                unknown()
            }
            _ => unknown(),
        }
    }
    fn bind(&mut self, target: &Node, names: BTreeSet<String>) {
        for name in stored_names(target) {
            self.bindings.insert(
                name,
                if kind(target) == "Name" {
                    names.clone()
                } else {
                    unknown()
                },
            );
        }
    }
    fn visit_body(&mut self, body: &[Node]) {
        for node in body {
            self.visit(node)
        }
    }
    fn generic(&mut self, node: &Node) {
        for child in children(node) {
            self.visit(child)
        }
    }
    fn function(&mut self, node: &Node) {
        let args = child(node, "args");
        for default in items(args, "defaults")
            .iter()
            .chain(items(args, "kw_defaults"))
        {
            if !default.is_null() {
                self.visit(default)
            }
        }
        if kind(node) != "Lambda" {
            self.visit_body(items(node, "decorator_list"));
            self.bindings.insert(s(node, "name").into(), unknown());
        }
        let parameters: Vec<_> = items(args, "posonlyargs")
            .iter()
            .chain(items(args, "args"))
            .chain(items(args, "kwonlyargs"))
            .chain(
                [child(args, "vararg"), child(args, "kwarg")]
                    .into_iter()
                    .filter(|n| !n.is_null()),
            )
            .collect();
        for parameter in &parameters {
            if !child(parameter, "annotation").is_null() {
                self.visit(child(parameter, "annotation"))
            }
        }
        let annotations: Bindings = parameters
            .iter()
            .map(|p| (s(p, "arg").into(), self.names(child(p, "annotation"))))
            .collect();
        let mut bindings = self
            .function_parent
            .as_ref()
            .unwrap_or(&self.bindings)
            .clone();
        let body = if kind(node) == "Lambda" {
            &[][..]
        } else {
            items(node, "body")
        };
        for name in local_names(body) {
            bindings.insert(name, unknown());
        }
        bindings.extend(annotations);
        for variadic in [child(args, "vararg"), child(args, "kwarg")] {
            if !variadic.is_null() {
                bindings.insert(s(variadic, "arg").into(), unknown());
            }
        }
        let mut resolver = self.child(bindings);
        if kind(node) == "Lambda" {
            resolver.visit(child(node, "body"))
        } else {
            resolver.visit_body(body)
        }
        self.references.extend(resolver.references);
    }
    fn branches(&mut self, branches: Vec<Vec<&Node>>) {
        let mut exits = Vec::new();
        for body in branches {
            let mut resolver = self.child(self.bindings.clone());
            resolver.function_parent = self.function_parent.clone();
            for statement in body {
                resolver.visit(statement)
            }
            self.references.extend(resolver.references);
            exits.push(resolver.bindings);
        }
        let keys: BTreeSet<_> = exits.iter().flat_map(|b| b.keys().cloned()).collect();
        for key in keys {
            let names = exits
                .iter()
                .flat_map(|b| b.get(&key).cloned().unwrap_or_else(unknown))
                .collect();
            self.bindings.insert(key, names);
        }
    }
    fn comprehension(&mut self, node: &Node) {
        let mut resolver = self.child(self.bindings.clone());
        for generator in items(node, "generators") {
            resolver.visit(child(generator, "iter"));
            resolver.bind(child(generator, "target"), unknown());
            resolver.visit_body(items(generator, "ifs"));
        }
        if kind(node) == "DictComp" {
            resolver.visit(child(node, "key"));
            resolver.visit(child(node, "value"));
        } else {
            resolver.visit(child(node, "elt"));
        }
        self.references.extend(resolver.references);
    }
    fn visit(&mut self, node: &Node) {
        if node.is_null() {
            return;
        }
        if is_expr(node) {
            self.references.insert(id(node), self.names(node));
        }
        match kind(node) {
            "Module" => {
                let mut summary = self.child(self.bindings.clone());
                for statement in items(node, "body") {
                    match kind(statement) {
                        "Import" | "ImportFrom" => summary.visit(statement),
                        "Assign" => {
                            let names = summary.names(child(statement, "value"));
                            for target in items(statement, "targets") {
                                summary.bind(target, names.clone())
                            }
                        }
                        "AnnAssign" => summary.bind(
                            child(statement, "target"),
                            summary.names(child(statement, "value")),
                        ),
                        "FunctionDef" | "AsyncFunctionDef" | "ClassDef" => {
                            summary
                                .bindings
                                .insert(s(statement, "name").into(), unknown());
                        }
                        _ => {
                            let mut locals_set = BTreeSet::new();
                            locals(statement, &mut locals_set);
                            for name in locals_set {
                                summary.bindings.insert(name, unknown());
                            }
                        }
                    }
                }
                self.function_parent = Some(summary.bindings);
                self.visit_body(items(node, "body"));
            }
            "Import" => {
                for alias in items(node, "names") {
                    let name = s(alias, "name");
                    let alias_name = s(alias, "asname");
                    let root = name.split('.').next().unwrap_or(name);
                    self.bindings.insert(
                        if alias_name.is_empty() {
                            root
                        } else {
                            alias_name
                        }
                        .into(),
                        singleton(if alias_name.is_empty() { root } else { name }),
                    );
                }
            }
            "ImportFrom" => {
                if let Some(module) = absolute_module(node, self.package)
                    && !module.is_empty()
                {
                    for alias in items(node, "names") {
                        let name = s(alias, "name");
                        if name != "*" {
                            let alias_name = s(alias, "asname");
                            self.bindings.insert(
                                if alias_name.is_empty() {
                                    name
                                } else {
                                    alias_name
                                }
                                .into(),
                                singleton(format!("{module}.{name}")),
                            );
                        }
                    }
                }
            }
            "Assign" => {
                self.visit(child(node, "value"));
                let names = self.names(child(node, "value"));
                for target in items(node, "targets") {
                    self.visit(target);
                    self.bind(target, names.clone());
                }
            }
            "AnnAssign" => {
                self.visit(child(node, "annotation"));
                self.visit(child(node, "value"));
                self.bind(
                    child(node, "target"),
                    self.names(if child(node, "value").is_null() {
                        child(node, "annotation")
                    } else {
                        child(node, "value")
                    }),
                );
            }
            "NamedExpr" => {
                self.visit(child(node, "value"));
                self.bind(child(node, "target"), self.names(child(node, "value")));
            }
            "AugAssign" => {
                self.generic(node);
                self.bind(child(node, "target"), unknown());
            }
            "Delete" => {
                for target in items(node, "targets") {
                    self.bind(target, unknown());
                }
            }
            "FunctionDef" | "AsyncFunctionDef" | "Lambda" => self.function(node),
            "ClassDef" => {
                for expression in items(node, "bases")
                    .iter()
                    .chain(items(node, "decorator_list"))
                {
                    self.visit(expression)
                }
                for keyword in items(node, "keywords") {
                    self.visit(child(keyword, "value"));
                }
                let mut resolver = self.child(self.bindings.clone());
                resolver.function_parent = Some(
                    self.function_parent
                        .as_ref()
                        .unwrap_or(&self.bindings)
                        .clone(),
                );
                resolver.visit_body(items(node, "body"));
                self.references.extend(resolver.references);
                self.bindings.insert(s(node, "name").into(), unknown());
            }
            "If" => {
                self.visit(child(node, "test"));
                self.branches(vec![
                    items(node, "body").iter().collect(),
                    items(node, "orelse").iter().collect(),
                ]);
            }
            "For" | "AsyncFor" => {
                self.visit(child(node, "iter"));
                self.bind(child(node, "target"), unknown());
                self.branches(vec![vec![], items(node, "body").iter().collect()]);
                self.visit_body(items(node, "orelse"));
            }
            "While" => {
                self.visit(child(node, "test"));
                self.branches(vec![vec![], items(node, "body").iter().collect()]);
                self.visit_body(items(node, "orelse"));
            }
            "Try" | "TryStar" => {
                for name in local_names(items(node, "body")) {
                    self.bindings.insert(name, unknown());
                }
                for handler in items(node, "handlers") {
                    if !child(handler, "name").is_null() {
                        self.bindings.insert(s(handler, "name").into(), unknown());
                    }
                }
                let mut branches = vec![
                    items(node, "body")
                        .iter()
                        .chain(items(node, "orelse"))
                        .collect(),
                ];
                branches.extend(
                    items(node, "handlers")
                        .iter()
                        .map(|h| items(h, "body").iter().collect()),
                );
                self.branches(branches);
                self.visit_body(items(node, "finalbody"));
            }
            "Match" => {
                self.visit(child(node, "subject"));
                for case in items(node, "cases") {
                    for capture in walk(child(case, "pattern")) {
                        let name = match kind(capture) {
                            "MatchAs" | "MatchStar" => s(capture, "name"),
                            "MatchMapping" => s(capture, "rest"),
                            _ => "",
                        };
                        if !name.is_empty() {
                            self.bindings.insert(name.into(), unknown());
                        }
                    }
                    self.visit(child(case, "guard"));
                }
                let mut branches = vec![vec![]];
                branches.extend(
                    items(node, "cases")
                        .iter()
                        .map(|c| items(c, "body").iter().collect()),
                );
                self.branches(branches);
            }
            "ListComp" | "SetComp" | "DictComp" | "GeneratorExp" => self.comprehension(node),
            _ => self.generic(node),
        }
    }
}
const BUILTINS: &str = "__loader__ bool memoryview bytearray bytes classmethod complex dict enumerate filter float frozenset property int list map object range reversed set slice staticmethod str super tuple type zip BaseException BaseExceptionGroup Exception GeneratorExit KeyboardInterrupt SystemExit ArithmeticError AssertionError AttributeError BufferError EOFError ImportError LookupError MemoryError NameError OSError ReferenceError RuntimeError StopAsyncIteration StopIteration SyntaxError SystemError TypeError ValueError Warning FloatingPointError OverflowError ZeroDivisionError BytesWarning DeprecationWarning EncodingWarning FutureWarning ImportWarning PendingDeprecationWarning ResourceWarning RuntimeWarning SyntaxWarning UnicodeWarning UserWarning BlockingIOError ChildProcessError ConnectionError FileExistsError FileNotFoundError InterruptedError IsADirectoryError NotADirectoryError PermissionError ProcessLookupError TimeoutError IndentationError _IncompleteInputError IndexError KeyError ModuleNotFoundError NotImplementedError PythonFinalizationError RecursionError UnboundLocalError UnicodeError BrokenPipeError ConnectionAbortedError ConnectionRefusedError ConnectionResetError TabError UnicodeDecodeError UnicodeEncodeError UnicodeTranslateError ExceptionGroup EnvironmentError IOError open print input getattr setattr delattr eval exec __import__";
pub fn resolve(tree: &Node, package: Option<&str>) -> Symbols {
    let _span = crate::profile::span("symbols");
    let bindings = BUILTINS
        .split_whitespace()
        .map(|name| (name.to_string(), singleton(format!("builtins.{name}"))))
        .collect();
    let mut resolver = Resolver::new(bindings, package);
    resolver.visit(tree);
    resolver.references
}

#[cfg(test)]
mod tests {
    use super::*;
    fn calls(source: &str) -> Vec<BTreeSet<String>> {
        let tree = ast::parse(source).unwrap();
        let symbols = resolve(&tree, Some("example.domain"));
        let mut calls: Vec<_> = walk(&tree)
            .into_iter()
            .filter(|n| kind(n) == "Call")
            .collect();
        calls.sort_by_key(|n| (n["lineno"].as_u64(), n["col_offset"].as_u64()));
        calls
            .into_iter()
            .map(|n| names(&symbols, child(n, "func")))
            .collect()
    }
    #[test]
    fn branches_keep_all_possible_aliases() {
        assert_eq!(
            calls(
                "import random\nimport time\nif condition:\n    clock = time.time\nelse:\n    clock = random.random\nclock()\n"
            ),
            vec![BTreeSet::from(["random.random".into(), "time.time".into()])]
        );
    }
    #[test]
    fn function_globals_see_later_rebinding_and_local_shadowing() {
        assert_eq!(
            calls("import time\ndef first():\n    time.time()\ntime = None\n"),
            vec![unknown()]
        );
        assert_eq!(
            calls("import time\ndef second():\n    time.time()\n    time = None\n"),
            vec![unknown()]
        );
    }
    #[test]
    fn classes_do_not_leak_bindings_to_methods() {
        assert_eq!(
            calls(
                "import time\nclass C:\n    time = None\n    def method(self):\n        time.time()\n"
            ),
            vec![singleton("time.time")]
        );
    }
    #[test]
    fn annotations_factories_and_comprehensions() {
        assert_eq!(
            calls(
                "from pathlib import Path\ndef f(path: 'Path'):\n    path.read_text()\n[Path() for Path in values]\nPath()\n"
            ),
            vec![
                singleton("pathlib.Path.read_text"),
                unknown(),
                singleton("pathlib.Path")
            ]
        );
        assert_eq!(
            calls("from .clock import now\nnow()\n"),
            vec![singleton("example.domain.clock.now")]
        );
    }
}
