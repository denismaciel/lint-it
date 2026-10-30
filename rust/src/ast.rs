//! Ruff's production parser with a small CPython-shaped adapter for rule parity.
use ruff_python_ast as py;
use ruff_text_size::{Ranged, TextRange, TextSize};
use serde_json::{Value, json};
use std::cell::Cell;
use std::collections::VecDeque;
pub type Node = Value;
pub use crate::model::ParseFailure;
pub fn kind(n: &Node) -> &str {
    s(n, "_type")
}
pub fn s<'a>(n: &'a Node, field: &str) -> &'a str {
    n.get(field).and_then(Value::as_str).unwrap_or("")
}
pub fn items<'a>(n: &'a Node, field: &str) -> &'a [Node] {
    n.get(field)
        .and_then(Value::as_array)
        .map(Vec::as_slice)
        .unwrap_or(&[])
}
pub fn child<'a>(n: &'a Node, field: &str) -> &'a Node {
    n.get(field).unwrap_or(&Value::Null)
}
pub fn id(n: &Node) -> usize {
    n.get("_id").and_then(Value::as_u64).unwrap_or(0) as usize
}
pub fn children(n: &Node) -> Vec<&Node> {
    let mut result = Vec::new();
    if let Some(fields) = n.as_object() {
        for value in fields.values() {
            if !kind(value).is_empty() {
                result.push(value);
            } else if let Some(values) = value.as_array() {
                result.extend(values.iter().filter(|v| !kind(v).is_empty()));
            }
        }
    }
    result
}
pub fn walk(n: &Node) -> Vec<&Node> {
    let mut queue = VecDeque::from([n]);
    let mut result = Vec::new();
    while let Some(n) = queue.pop_front() {
        result.push(n);
        queue.extend(children(n));
    }
    result
}
pub fn parse(source: &str) -> Result<Node, ParseFailure> {
    let adapter = Adapter::new(source);
    let parsed = ruff_python_parser::parse_module(source).map_err(|error| {
        let mut offset = error.location.start().to_usize();
        let mut message = parse_error_message(&error.error);
        // Ruff tokenizes a numeric prefix and adjacent identifier separately;
        // CPython reports the malformed number at its final decimal digit.
        if matches!(
            error.error,
            ruff_python_parser::ParseErrorType::SimpleStatementsOnSameLine
        ) && offset > 0
            && source.as_bytes()[offset - 1].is_ascii_digit()
            && source[offset..]
                .chars()
                .next()
                .is_some_and(|c| c.is_alphabetic() || c == '_')
        {
            offset -= 1;
            message = "invalid decimal literal".into();
        }
        let (line, column) = adapter.position(offset);
        ParseFailure {
            line,
            column,
            message,
        }
    })?;
    Ok(adapter.node(
        "Module",
        parsed.syntax().range,
        json!({"body":adapter.stmts(&parsed.syntax().body),"type_ignores":[]}),
    ))
}
pub fn parse_expression(source: &str) -> Option<Node> {
    let parsed = ruff_python_parser::parse_expression(source).ok()?;
    Some(Adapter::new(source).expr(&parsed.syntax().body))
}
// Normalize common CPython diagnostics. More specialized Ruff lexer diagnostics
// intentionally retain their original detail rather than guessing CPython text.
fn parse_error_message(error: &ruff_python_parser::ParseErrorType) -> String {
    use ruff_python_parser::ParseErrorType::*;
    match error {
        OtherError(message) if message.starts_with("Expected ") => "invalid syntax".into(),
        UnexpectedIndentation => "unexpected indent".into(),
        NonDefaultParamAfterDefaultParam => {
            "parameter without a default follows parameter with a default".into()
        }
        PositionalAfterKeywordArgument => "positional argument follows keyword argument".into(),
        PositionalAfterKeywordUnpacking => {
            "positional argument follows keyword argument unpacking".into()
        }
        ExpectedExpression
        | ExpectedToken { .. }
        | EmptySlice
        | EmptyGlobalNames
        | EmptyNonlocalNames
        | EmptyDeleteTargets
        | EmptyImportNames
        | EmptyTypeParams
        | SimpleStatementsOnSameLine
        | SimpleAndCompoundStatementOnSameLine
        | UnexpectedExpressionToken
        | UnexpectedTokenAfterAsync(_) => "invalid syntax".into(),
        _ => error.to_string(),
    }
}
struct Adapter<'a> {
    source: &'a str,
    lines: Vec<usize>,
    next: Cell<usize>,
}
impl<'a> Adapter<'a> {
    fn new(source: &'a str) -> Self {
        let mut lines = vec![0];
        lines.extend(
            source
                .bytes()
                .enumerate()
                .filter_map(|(i, b)| (b == b'\n').then_some(i + 1)),
        );
        Self {
            source,
            lines,
            next: Cell::new(1),
        }
    }
    fn position(&self, offset: usize) -> (usize, usize) {
        let index = self.lines.partition_point(|p| *p <= offset) - 1;
        (index + 1, offset - self.lines[index])
    }
    fn node(&self, name: &str, range: TextRange, mut fields: Node) -> Node {
        let (line, col) = self.position(range.start().to_usize());
        let (end_line, end_col) = self.position(range.end().to_usize());
        let map = fields.as_object_mut().unwrap();
        map.insert("_type".into(), json!(name));
        map.insert("_id".into(), json!(self.next.get()));
        self.next.set(self.next.get() + 1);
        map.insert("lineno".into(), json!(line));
        map.insert("col_offset".into(), json!(col));
        map.insert("end_lineno".into(), json!(end_line));
        map.insert("end_col_offset".into(), json!(end_col));
        fields
    }
    fn tag(&self, value: impl std::fmt::Debug) -> Node {
        self.node(&format!("{value:?}"), TextRange::default(), json!({}))
    }
    fn opt(&self, e: Option<&py::Expr>) -> Node {
        e.map(|e| self.expr(e)).unwrap_or(Value::Null)
    }
    fn exprs(&self, e: &[py::Expr]) -> Vec<Node> {
        e.iter().map(|e| self.expr(e)).collect()
    }
    fn stmts(&self, s: &[py::Stmt]) -> Vec<Node> {
        s.iter().map(|s| self.stmt(s)).collect()
    }
    fn aliases(&self, a: &[py::Alias]) -> Vec<Node> {
        a.iter()
            .map(|a| {
                self.node(
                    "alias",
                    a.range,
                    json!({"name":a.name.as_str(),"asname":a.asname.as_ref().map(|s|s.as_str())}),
                )
            })
            .collect()
    }
    fn keywords(&self, k: &[py::Keyword]) -> Vec<Node> {
        k.iter()
            .map(|k| {
                self.node(
                    "keyword",
                    k.range,
                    json!({"arg":k.arg.as_ref().map(|s|s.as_str()),"value":self.expr(&k.value)}),
                )
            })
            .collect()
    }
    fn parameter(&self, p: &py::Parameter) -> Node {
        self.node("arg",TextRange::new(p.name.range().start(),p.range.end()),json!({"arg":p.name.as_str(),"annotation":self.opt(p.annotation.as_deref()),"type_comment":null}))
    }
    fn parameters(&self, p: Option<&py::Parameters>) -> Node {
        let empty = py::Parameters::default();
        let p = p.unwrap_or(&empty);
        self.node("arguments",p.range,json!({"posonlyargs":p.posonlyargs.iter().map(|a|self.parameter(&a.parameter)).collect::<Vec<_>>(),"args":p.args.iter().map(|a|self.parameter(&a.parameter)).collect::<Vec<_>>(),"vararg":p.vararg.as_deref().map(|a|self.parameter(a)),"kwonlyargs":p.kwonlyargs.iter().map(|a|self.parameter(&a.parameter)).collect::<Vec<_>>(),"kw_defaults":p.kwonlyargs.iter().map(|a|self.opt(a.default.as_deref())).collect::<Vec<_>>(),"kwarg":p.kwarg.as_deref().map(|a|self.parameter(a)),"defaults":p.posonlyargs.iter().chain(&p.args).filter_map(|a|a.default.as_deref()).map(|a|self.expr(a)).collect::<Vec<_>>()}))
    }
    fn types(&self, p: Option<&py::TypeParams>) -> Vec<Node> {
        p.map(|p|p.iter().map(|p|match p {
        py::TypeParam::TypeVar(p)=>self.node("TypeVar",p.range,json!({"name":p.name.as_str(),"bound":self.opt(p.bound.as_deref()),"default_value":self.opt(p.default.as_deref())})),
        py::TypeParam::TypeVarTuple(p)=>self.node("TypeVarTuple",p.range,json!({"name":p.name.as_str(),"default_value":self.opt(p.default.as_deref())})),
        py::TypeParam::ParamSpec(p)=>self.node("ParamSpec",p.range,json!({"name":p.name.as_str(),"default_value":self.opt(p.default.as_deref())})),
    }).collect()).unwrap_or_default()
    }
    fn stmt(&self, s: &py::Stmt) -> Node {
        let (name, fields) = match s {
            py::Stmt::FunctionDef(n) => (
                if n.is_async {
                    "AsyncFunctionDef"
                } else {
                    "FunctionDef"
                },
                json!({"name":n.name.as_str(),"args":self.parameters(Some(&n.parameters)),"body":self.stmts(&n.body),"decorator_list":n.decorator_list.iter().map(|d|self.expr(&d.expression)).collect::<Vec<_>>(),"returns":self.opt(n.returns.as_deref()),"type_comment":null,"type_params":self.types(n.type_params.as_deref())}),
            ),
            py::Stmt::ClassDef(n) => (
                "ClassDef",
                json!({"name":n.name.as_str(),"bases":n.arguments.as_ref().map(|a|self.exprs(&a.args)).unwrap_or_default(),"keywords":n.arguments.as_ref().map(|a|self.keywords(&a.keywords)).unwrap_or_default(),"body":self.stmts(&n.body),"decorator_list":n.decorator_list.iter().map(|d|self.expr(&d.expression)).collect::<Vec<_>>(),"type_params":self.types(n.type_params.as_deref())}),
            ),
            py::Stmt::Return(n) => ("Return", json!({"value":self.opt(n.value.as_deref())})),
            py::Stmt::Delete(n) => ("Delete", json!({"targets":self.exprs(&n.targets)})),
            py::Stmt::TypeAlias(n) => (
                "TypeAlias",
                json!({"name":self.expr(&n.name),"type_params":self.types(n.type_params.as_deref()),"value":self.expr(&n.value)}),
            ),
            py::Stmt::Assign(n) => (
                "Assign",
                json!({"targets":self.exprs(&n.targets),"value":self.expr(&n.value),"type_comment":null}),
            ),
            py::Stmt::AugAssign(n) => (
                "AugAssign",
                json!({"target":self.expr(&n.target),"op":self.tag(n.op),"value":self.expr(&n.value)}),
            ),
            py::Stmt::AnnAssign(n) => (
                "AnnAssign",
                json!({"target":self.expr(&n.target),"annotation":self.expr(&n.annotation),"value":self.opt(n.value.as_deref()),"simple":usize::from(n.simple)}),
            ),
            py::Stmt::For(n) => (
                if n.is_async { "AsyncFor" } else { "For" },
                json!({"target":self.expr(&n.target),"iter":self.expr(&n.iter),"body":self.stmts(&n.body),"orelse":self.stmts(&n.orelse),"type_comment":null}),
            ),
            py::Stmt::While(n) => (
                "While",
                json!({"test":self.expr(&n.test),"body":self.stmts(&n.body),"orelse":self.stmts(&n.orelse)}),
            ),
            py::Stmt::If(n) => {
                let mut orelse = vec![];
                for c in n.elif_else_clauses.iter().rev() {
                    if let Some(test) = &c.test {
                        orelse=vec![self.node("If",c.range,json!({"test":self.expr(test),"body":self.stmts(&c.body),"orelse":orelse}))];
                    } else {
                        orelse = self.stmts(&c.body);
                    }
                }
                (
                    "If",
                    json!({"test":self.expr(&n.test),"body":self.stmts(&n.body),"orelse":orelse}),
                )
            }
            py::Stmt::With(n) => (
                if n.is_async { "AsyncWith" } else { "With" },
                json!({"items":n.items.iter().map(|i|self.node("withitem",i.range,json!({"context_expr":self.expr(&i.context_expr),"optional_vars":self.opt(i.optional_vars.as_deref())}))).collect::<Vec<_>>(),"body":self.stmts(&n.body),"type_comment":null}),
            ),
            py::Stmt::Match(n) => (
                "Match",
                json!({"subject":self.expr(&n.subject),"cases":n.cases.iter().map(|c|self.node("match_case",c.range,json!({"pattern":self.pattern(&c.pattern),"guard":self.opt(c.guard.as_deref()),"body":self.stmts(&c.body)}))).collect::<Vec<_>>()}),
            ),
            py::Stmt::Raise(n) => (
                "Raise",
                json!({"exc":self.opt(n.exc.as_deref()),"cause":self.opt(n.cause.as_deref())}),
            ),
            py::Stmt::Try(n) => (
                if n.is_star { "TryStar" } else { "Try" },
                json!({"body":self.stmts(&n.body),"handlers":n.handlers.iter().map(|h|{let py::ExceptHandler::ExceptHandler(h)=h;self.node("ExceptHandler",h.range,json!({"type":self.opt(h.type_.as_deref()),"name":h.name.as_ref().map(|s|s.as_str()),"body":self.stmts(&h.body)}))}).collect::<Vec<_>>(),"orelse":self.stmts(&n.orelse),"finalbody":self.stmts(&n.finalbody)}),
            ),
            py::Stmt::Assert(n) => (
                "Assert",
                json!({"test":self.expr(&n.test),"msg":self.opt(n.msg.as_deref())}),
            ),
            py::Stmt::Import(n) => ("Import", json!({"names":self.aliases(&n.names)})),
            py::Stmt::ImportFrom(n) => (
                "ImportFrom",
                json!({"module":n.module.as_ref().map(|s|s.as_str()),"names":self.aliases(&n.names),"level":n.level}),
            ),
            py::Stmt::Global(n) => (
                "Global",
                json!({"names":n.names.iter().map(|s|s.as_str()).collect::<Vec<_>>()}),
            ),
            py::Stmt::Nonlocal(n) => (
                "Nonlocal",
                json!({"names":n.names.iter().map(|s|s.as_str()).collect::<Vec<_>>()}),
            ),
            py::Stmt::Expr(n) => ("Expr", json!({"value":self.expr(&n.value)})),
            py::Stmt::Pass(_) => ("Pass", json!({})),
            py::Stmt::Break(_) => ("Break", json!({})),
            py::Stmt::Continue(_) => ("Continue", json!({})),
            py::Stmt::IpyEscapeCommand(_) => ("IpyEscapeCommand", json!({})),
        };
        // Ruff includes decorators in declaration ranges; CPython starts at
        // the declaration keyword. Search only the prefix before the name.
        let range = match s {
            py::Stmt::FunctionDef(n) => self.declaration_range(
                s.range(),
                n.name.range().start(),
                if n.is_async { "async" } else { "def" },
            ),
            py::Stmt::ClassDef(n) => {
                self.declaration_range(s.range(), n.name.range().start(), "class")
            }
            _ => s.range(),
        };
        self.node(name, range, fields)
    }
    fn declaration_range(&self, range: TextRange, name: TextSize, keyword: &str) -> TextRange {
        let prefix = &self.source[range.start().to_usize()..name.to_usize()];
        let start = range.start() + TextSize::try_from(prefix.rfind(keyword).unwrap_or(0)).unwrap();
        TextRange::new(start, range.end())
    }
    fn generators(&self, g: &[py::Comprehension]) -> Vec<Node> {
        g.iter().map(|g|self.node("comprehension",g.range,json!({"target":self.expr(&g.target),"iter":self.expr(&g.iter),"ifs":self.exprs(&g.ifs),"is_async":usize::from(g.is_async)}))).collect()
    }
    fn interpolated(&self, e: &py::InterpolatedStringElement) -> Node {
        match e {
        py::InterpolatedStringElement::Literal(n)=>self.node("Constant",n.range,json!({"value":n.value.as_ref(),"kind":null})),
        py::InterpolatedStringElement::Interpolation(n)=>self.node("FormattedValue",n.range,json!({"value":self.expr(&n.expression),"conversion":n.conversion as i32,"format_spec":n.format_spec.as_ref().map(|f|self.node("JoinedStr",TextRange::new(f.range.start() - TextSize::from(1), f.range.end()),json!({"values":f.elements.iter().map(|e|self.interpolated(e)).collect::<Vec<_>>()})))})),
    }
    }
    fn set_range(&self, node: &mut Node, range: TextRange) {
        let (line, col) = self.position(range.start().to_usize());
        let (end_line, end_col) = self.position(range.end().to_usize());
        node["lineno"] = json!(line);
        node["col_offset"] = json!(col);
        node["end_lineno"] = json!(end_line);
        node["end_col_offset"] = json!(end_col);
    }
    fn fstring(&self, value: &py::FStringValue) -> Vec<Node> {
        let mut values = Vec::new();
        for part in value.iter() {
            match part {
                py::FStringPartRef::Literal(n) => values.push(self.node(
                    "Constant",
                    n.range,
                    json!({"value":n.as_str(),"kind":null}),
                )),
                py::FStringPartRef::FString(n) => {
                    for element in &n.elements {
                        if let py::InterpolatedStringElement::Interpolation(interpolation) = element
                            && let Some(debug) = &interpolation.debug_text
                        {
                            let start = interpolation.range.start() + TextSize::from(1);
                            values.push(self.node(
                                "Constant",
                                TextRange::new(
                                    start,
                                    start + TextSize::try_from(debug.as_str().len()).unwrap(),
                                ),
                                json!({"value":debug.as_str(),"kind":null}),
                            ));
                        }
                        values.push(self.interpolated(element));
                    }
                }
            }
        }
        let mut merged: Vec<Node> = Vec::new();
        for node in values {
            if kind(&node) == "Constant"
                && let Some(last) = merged.last_mut()
                && kind(last) == "Constant"
            {
                last["value"] = json!(format!("{}{}", s(last, "value"), s(&node, "value")));
                last["end_lineno"] = node["end_lineno"].clone();
                last["end_col_offset"] = node["end_col_offset"].clone();
            } else {
                merged.push(node)
            }
        }
        merged
    }
    fn expr(&self, e: &py::Expr) -> Node {
        let (name, fields) = match e {
            py::Expr::BoolOp(n) => (
                "BoolOp",
                json!({"op":self.tag(n.op),"values":self.exprs(&n.values)}),
            ),
            py::Expr::Named(n) => (
                "NamedExpr",
                json!({"target":self.expr(&n.target),"value":self.expr(&n.value)}),
            ),
            py::Expr::BinOp(n) => (
                "BinOp",
                json!({"left":self.expr(&n.left),"op":self.tag(n.op),"right":self.expr(&n.right)}),
            ),
            py::Expr::UnaryOp(n) => (
                "UnaryOp",
                json!({"op":self.tag(n.op),"operand":self.expr(&n.operand)}),
            ),
            py::Expr::Lambda(n) => (
                "Lambda",
                json!({"args":self.parameters(n.parameters.as_deref()),"body":self.expr(&n.body)}),
            ),
            py::Expr::If(n) => (
                "IfExp",
                json!({"test":self.expr(&n.test),"body":self.expr(&n.body),"orelse":self.expr(&n.orelse)}),
            ),
            py::Expr::Dict(n) => (
                "Dict",
                json!({"keys":n.items.iter().map(|i|self.opt(i.key.as_ref())).collect::<Vec<_>>(),"values":n.items.iter().map(|i|self.expr(&i.value)).collect::<Vec<_>>()}),
            ),
            py::Expr::Set(n) => ("Set", json!({"elts":self.exprs(&n.elts)})),
            py::Expr::ListComp(n) => (
                "ListComp",
                json!({"elt":self.expr(&n.elt),"generators":self.generators(&n.generators)}),
            ),
            py::Expr::SetComp(n) => (
                "SetComp",
                json!({"elt":self.expr(&n.elt),"generators":self.generators(&n.generators)}),
            ),
            py::Expr::DictComp(n) => (
                "DictComp",
                json!({"key":self.opt(n.key.as_deref()),"value":self.expr(&n.value),"generators":self.generators(&n.generators)}),
            ),
            py::Expr::Generator(n) => (
                "GeneratorExp",
                json!({"elt":self.expr(&n.elt),"generators":self.generators(&n.generators)}),
            ),
            py::Expr::Await(n) => ("Await", json!({"value":self.expr(&n.value)})),
            py::Expr::Yield(n) => ("Yield", json!({"value":self.opt(n.value.as_deref())})),
            py::Expr::YieldFrom(n) => ("YieldFrom", json!({"value":self.expr(&n.value)})),
            py::Expr::Compare(n) => (
                "Compare",
                json!({"left":self.expr(&n.operands[0]),"ops":n.ops.iter().map(|op|self.tag(op)).collect::<Vec<_>>(),"comparators":self.exprs(&n.operands[1..])}),
            ),
            py::Expr::Call(n) => (
                "Call",
                json!({"func":self.expr(&n.func),"args":n.arguments.args.iter().map(|arg|{let mut node=self.expr(arg);if matches!(arg,py::Expr::Generator(g) if !g.parenthesized){self.set_range(&mut node,n.arguments.range);}node}).collect::<Vec<_>>(),"keywords":self.keywords(&n.arguments.keywords)}),
            ),
            py::Expr::FString(n) => ("JoinedStr", json!({"values":self.fstring(&n.value)})),
            py::Expr::TString(n) => (
                "TemplateStr",
                json!({"values":n.value.elements().map(|e|self.interpolated(e)).collect::<Vec<_>>()}),
            ),
            py::Expr::StringLiteral(n) => {
                ("Constant", json!({"value":n.value.to_str(),"kind":null}))
            }
            py::Expr::BytesLiteral(_) => ("Constant", json!({"value":{"_bytes":true},"kind":null})),
            py::Expr::NumberLiteral(n) => {
                let value = match &n.value {
                    py::Number::Int(i) => i
                        .as_i64()
                        .map(|i| json!(i))
                        .unwrap_or_else(|| json!({"_integer":i.to_string()})),
                    py::Number::Float(f) => json!(f),
                    py::Number::Complex { real, imag } => json!({"_complex":[real,imag]}),
                };
                ("Constant", json!({"value":value,"kind":null}))
            }
            py::Expr::BooleanLiteral(n) => ("Constant", json!({"value":n.value,"kind":null})),
            py::Expr::NoneLiteral(_) => ("Constant", json!({"value":null,"kind":null})),
            py::Expr::EllipsisLiteral(_) => {
                ("Constant", json!({"value":{"_ellipsis":true},"kind":null}))
            }
            py::Expr::Attribute(n) => (
                "Attribute",
                json!({"value":self.expr(&n.value),"attr":n.attr.as_str(),"ctx":self.tag(n.ctx)}),
            ),
            py::Expr::Subscript(n) => (
                "Subscript",
                json!({"value":self.expr(&n.value),"slice":self.expr(&n.slice),"ctx":self.tag(n.ctx)}),
            ),
            py::Expr::Starred(n) => (
                "Starred",
                json!({"value":self.expr(&n.value),"ctx":self.tag(n.ctx)}),
            ),
            py::Expr::Name(n) => ("Name", json!({"id":n.id.as_str(),"ctx":self.tag(n.ctx)})),
            py::Expr::List(n) => (
                "List",
                json!({"elts":self.exprs(&n.elts),"ctx":self.tag(n.ctx)}),
            ),
            py::Expr::Tuple(n) => (
                "Tuple",
                json!({"elts":self.exprs(&n.elts),"ctx":self.tag(n.ctx)}),
            ),
            py::Expr::Slice(n) => (
                "Slice",
                json!({"lower":self.opt(n.lower.as_deref()),"upper":self.opt(n.upper.as_deref()),"step":self.opt(n.step.as_deref())}),
            ),
            py::Expr::IpyEscapeCommand(_) => ("IpyEscapeCommand", json!({})),
        };
        self.node(name, e.range(), fields)
    }
    fn pattern(&self, p: &py::Pattern) -> Node {
        let (name, fields) = match p {
            py::Pattern::MatchValue(n) => ("MatchValue", json!({"value":self.expr(&n.value)})),
            py::Pattern::MatchSingleton(n) => (
                "MatchSingleton",
                json!({"value":match n.value {py::Singleton::None=>Value::Null,py::Singleton::True=>json!(true),py::Singleton::False=>json!(false)}}),
            ),
            py::Pattern::MatchSequence(n) => (
                "MatchSequence",
                json!({"patterns":n.patterns.iter().map(|p|self.pattern(p)).collect::<Vec<_>>()}),
            ),
            py::Pattern::MatchMapping(n) => (
                "MatchMapping",
                json!({"keys":self.exprs(&n.keys),"patterns":n.patterns.iter().map(|p|self.pattern(p)).collect::<Vec<_>>(),"rest":n.rest.as_ref().map(|s|s.as_str())}),
            ),
            py::Pattern::MatchClass(n) => (
                "MatchClass",
                json!({"cls":self.expr(&n.cls),"patterns":n.arguments.patterns.iter().map(|p|self.pattern(p)).collect::<Vec<_>>(),"kwd_attrs":n.arguments.keywords.iter().map(|k|k.attr.as_str()).collect::<Vec<_>>(),"kwd_patterns":n.arguments.keywords.iter().map(|k|self.pattern(&k.pattern)).collect::<Vec<_>>()}),
            ),
            py::Pattern::MatchStar(n) => (
                "MatchStar",
                json!({"name":n.name.as_ref().map(|s|s.as_str())}),
            ),
            py::Pattern::MatchAs(n) => (
                "MatchAs",
                json!({"pattern":n.pattern.as_ref().map(|p|self.pattern(p)),"name":n.name.as_ref().map(|s|s.as_str())}),
            ),
            py::Pattern::MatchOr(n) => (
                "MatchOr",
                json!({"patterns":n.patterns.iter().map(|p|self.pattern(p)).collect::<Vec<_>>()}),
            ),
        };
        self.node(name, p.range(), fields)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn locations_use_utf8_bytes_and_generator_parentheses() {
        let tree = parse("é = consume(x for x in values)\n").unwrap();
        let nodes = walk(&tree);
        let call = nodes.iter().find(|n| kind(n) == "Call").unwrap();
        assert_eq!(call["col_offset"], 5);
        let generator = nodes.iter().find(|n| kind(n) == "GeneratorExp").unwrap();
        assert_eq!(generator["col_offset"], 12);
        let ids: std::collections::BTreeSet<_> = nodes.iter().map(|n| id(n)).collect();
        assert_eq!(ids.len(), nodes.len());
    }
    #[test]
    fn fstrings_merge_literals_and_keep_nested_expressions() {
        let tree = parse("value = 'before' f'a{clock.now():03}' 'after'\n").unwrap();
        let value = child(&items(&tree, "body")[0], "value");
        assert_eq!(s(&items(value, "values")[0], "value"), "beforea");
        assert_eq!(s(&items(value, "values")[2], "value"), "after");
        assert_eq!(walk(value).iter().filter(|n| kind(n) == "Call").count(), 1);
    }
    #[test]
    fn declarations_and_variadics_exclude_decorators_and_stars() {
        let tree=parse("@decorate\nclass  C:\n    @decorate\n    async def f(*args: int, **kwargs: str): pass\n").unwrap();
        let class = &items(&tree, "body")[0];
        assert_eq!(class["lineno"], 2);
        assert_eq!(class["col_offset"], 0);
        let function = &items(class, "body")[0];
        assert_eq!(function["lineno"], 4);
        assert_eq!(function["col_offset"], 4);
        let args = child(function, "args");
        assert_eq!(child(args, "vararg")["col_offset"], 17);
        assert_eq!(child(args, "kwarg")["col_offset"], 30);
    }
    #[test]
    fn malformed_decimal_literal_matches_cpython() {
        for (source, column) in [
            ("1syntax_error", 0),
            ("123abc", 2),
            ("x = 12abc", 5),
            ("1.2abc", 2),
        ] {
            let error = parse(source).unwrap_err();
            assert_eq!(
                (error.line, error.column, error.message.as_str()),
                (1, column, "invalid decimal literal")
            );
        }
        let error = parse("\n\n1syntax_error  # NOQA\n").unwrap_err();
        assert_eq!((error.line, error.column), (3, 0));
    }
    #[test]
    fn syntax_error_uses_zero_based_column() {
        let error = parse("def broken(:\n").unwrap_err();
        assert_eq!(
            (error.line, error.column, error.message.as_str()),
            (1, 11, "invalid syntax")
        );
    }
}
