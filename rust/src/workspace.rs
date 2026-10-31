use crate::{
    ast::{self, ParseFailure},
    model::{Classification, Source},
    symbols,
};
use rayon::prelude::*;
use serde_json::{Value, json};
use std::{
    collections::{BTreeMap, BTreeSet, HashMap},
    path::{Path, PathBuf},
    sync::{Arc, Mutex, OnceLock},
};
#[derive(Debug, Clone)]
pub struct CustomLayer {
    pub name: String,
    pub base: String,
    pub deterministic: bool,
}
#[derive(Debug, Clone)]
pub struct AllowedDependency {
    pub modules: Vec<String>,
    pub layers: BTreeSet<String>,
    pub reason: String,
}
#[derive(Debug, Clone)]
pub struct Policy {
    pub layer_dependencies: BTreeMap<String, BTreeSet<String>>,
    pub forbidden_imports: BTreeMap<String, BTreeSet<String>>,
    pub forbidden_calls: BTreeMap<String, BTreeSet<String>>,
    pub custom_layers: BTreeMap<String, CustomLayer>,
    pub allowed_dependencies: Vec<AllowedDependency>,
    pub predicate_prefixes: Vec<String>,
    pub outcome_suffixes: Vec<String>,
    pub allowed_bases: BTreeSet<String>,
    pub effectful_types: BTreeSet<String>,
    pub clock_modules: BTreeSet<String>,
    pub domain_dependencies: BTreeMap<String, BTreeSet<String>>,
}
impl Policy {
    pub fn base<'a>(&'a self, layer: &'a str) -> &'a str {
        self.custom_layers
            .get(layer)
            .map_or(layer, |c| c.base.as_str())
    }
    pub fn is_a(&self, layer: &str, targets: &BTreeSet<String>) -> bool {
        targets.contains(layer) || targets.contains(self.base(layer))
    }
    pub fn allows_dependency(&self, importer: &str, module: &str) -> bool {
        self.allowed_dependencies.iter().any(|a| {
            (a.layers.is_empty() || self.is_a(importer, &a.layers))
                && matches_name(module, &a.modules)
        })
    }
}
#[derive(Debug, Clone)]
pub struct Package {
    pub root: PathBuf,
    pub kind: String,
    pub layout: String,
    pub layers: Vec<(String, String)>,
    pub overrides: Vec<Value>,
    pub dependency_overrides: Vec<Value>,
}
#[derive(Debug, Clone)]
pub struct Ignore {
    pub rules: Vec<String>,
    pub paths: Vec<String>,
    pub layers: BTreeSet<String>,
    pub reason: String,
}
type CachedImport = (ast::Node, String, Option<String>);
#[derive(Default)]
struct SourceImports {
    top: OnceLock<Vec<CachedImport>>,
    initialization: OnceLock<Vec<(String, Option<String>)>>,
}
type LoadKey = (String, Option<String>);
pub struct Workspace {
    loaded_cache: Mutex<HashMap<LoadKey, Vec<usize>>>,
    import_cache: HashMap<PathBuf, SourceImports>,
    module_index: HashMap<String, usize>,
    pub root: PathBuf,
    pub manifest: Option<PathBuf>,
    pub packages: Vec<Package>,
    pub sources: Vec<Source>,
    pub parse_failures: Vec<(PathBuf, ParseFailure)>,
    pub policy: Policy,
    pub ignores: Vec<Ignore>,
    pub baseline_path: Option<PathBuf>,
    pub baseline: BTreeMap<(String, String, String), usize>,
    pub override_budget: usize,
    pub dependency_override_budget: usize,
}
pub fn matches_name<I, S>(name: &str, patterns: I) -> bool
where
    I: IntoIterator<Item = S>,
    S: AsRef<str>,
{
    patterns.into_iter().any(|p| {
        let p = p.as_ref();
        name == p || (p.ends_with(".*") && name.starts_with(&p[..p.len() - 1]))
    })
}
pub fn matches_glob(path: &str, pattern: &str) -> bool {
    static CACHE: OnceLock<Mutex<HashMap<String, Arc<regex::Regex>>>> = OnceLock::new();
    let cache = CACHE.get_or_init(Default::default);
    let mut cache = cache.lock().unwrap();
    let re = cache
        .entry(pattern.into())
        .or_insert_with(|| {
            let parts: Vec<_> = pattern.split('/').collect();
            let mut r = String::from("\\A");
            for (i, p) in parts.iter().enumerate() {
                let last = i + 1 == parts.len();
                if *p == "**" {
                    r.push_str(if last {
                        "(?:[^/]+/)*[^/]+"
                    } else {
                        "(?:[^/]+/)*"
                    });
                    continue;
                }
                let chars: Vec<_> = p.chars().collect();
                let mut j = 0;
                while j < chars.len() {
                    match chars[j] {
                        '*' => r.push_str("[^/]*"),
                        '?' => r.push_str("[^/]"),
                        '[' => {
                            if let Some(end) = (j + 2..chars.len()).find(|&k| chars[k] == ']') {
                                r.push('[');
                                let mut start = j + 1;
                                if chars[start] == '!' {
                                    r.push('^');
                                    start += 1;
                                }
                                for c in &chars[start..end] {
                                    if *c == '-' {
                                        r.push('-')
                                    } else {
                                        r.push_str(&regex::escape(&c.to_string()))
                                    }
                                }
                                r.push(']');
                                j = end;
                            } else {
                                r.push_str("\\[")
                            }
                        }
                        c => r.push_str(&regex::escape(&c.to_string())),
                    }
                    j += 1;
                }
                if !last {
                    r.push('/')
                }
            }
            r.push_str("\\z");
            Arc::new(regex::Regex::new(&r).unwrap_or_else(|_| regex::Regex::new("a^").unwrap()))
        })
        .clone();
    drop(cache);
    re.is_match(path)
}
const LAYERS: &[&str] = &[
    "core",
    "port",
    "shell",
    "adapter",
    "router",
    "boundary",
    "transaction",
    "test",
    "marker",
];
fn st(v: &Value) -> &str {
    v.as_str().unwrap_or("")
}
fn string(v: &Value, f: &str) -> Result<String, String> {
    v.as_str()
        .filter(|s| !s.trim().is_empty())
        .map(|s| s.trim().to_owned())
        .ok_or_else(|| format!("{f} must be a non-empty string"))
}
fn strings(v: &Value, f: &str) -> Result<Vec<String>, String> {
    v.as_array()
        .filter(|a| a.iter().all(|v| v.as_str().is_some_and(|s| !s.is_empty())))
        .map(|a| a.iter().map(|v| st(v).into()).collect())
        .ok_or_else(|| format!("{f} must be an array of non-empty strings"))
}
fn list(v: &Value, f: &str) -> Result<Vec<String>, String> {
    if v.is_null() {
        Ok(vec![])
    } else {
        strings(v, f)
    }
}
fn table<'a>(v: &'a Value, f: &str) -> Result<Vec<(&'a String, &'a Value)>, String> {
    if v.is_null() {
        Ok(vec![])
    } else {
        v.as_object()
            .map(|o| o.iter().collect())
            .ok_or_else(|| format!("{f} must be a table"))
    }
}
fn tables<'a>(v: &'a Value, f: &str) -> Result<Vec<&'a Value>, String> {
    if v.is_null() {
        Ok(vec![])
    } else {
        v.as_array()
            .filter(|a| a.iter().all(Value::is_object))
            .map(|a| a.iter().collect())
            .ok_or_else(|| format!("{f} must be an array of tables"))
    }
}
fn keys(v: &Value, allowed: &[&str], field: &str) -> Result<(), String> {
    let mut bad: Vec<_> = table(v, field)?
        .into_iter()
        .map(|(k, _)| k.as_str())
        .filter(|k| !allowed.contains(k))
        .collect();
    bad.sort();
    if bad.is_empty() {
        Ok(())
    } else {
        Err(format!("unknown {field} field: {}", bad.join(", ")))
    }
}
fn choice(v: &Value, f: &str, choices: &[String]) -> Result<String, String> {
    let s = string(v, f)?;
    if choices.contains(&s) {
        Ok(s)
    } else {
        Err(format!(
            "{f} must be one of: {}; got '{s}'",
            choices.join(", ")
        ))
    }
}
fn rel(v: &Value, f: &str) -> Result<String, String> {
    let s = v
        .as_str()
        .filter(|s| !s.trim().is_empty())
        .ok_or_else(|| format!("{f} must be a non-empty relative path"))?;
    if s.starts_with('/') || s.split('/').any(|s| s == "..") {
        return Err(format!("{f} must be a relative path inside the workspace"));
    }
    let parts: Vec<_> = s
        .split('/')
        .filter(|s| !s.is_empty() && *s != ".")
        .collect();
    Ok(if parts.is_empty() {
        ".".into()
    } else {
        parts.join("/")
    })
}
fn pyglob(v: &Value, f: &str) -> Result<String, String> {
    let s = rel(v, f)?;
    if !s.ends_with(".py") {
        Err(format!("{f} must select Python files: {s}"))
    } else {
        Ok(s)
    }
}
fn qualified(v: &Value, f: &str, wild: bool) -> Result<BTreeSet<String>, String> {
    let names = list(v, f)?;
    let bad: Vec<_> = names
        .iter()
        .filter(|n| {
            !n.strip_suffix(if wild { ".*" } else { "\0" })
                .unwrap_or(n)
                .split('.')
                .all(identifier)
        })
        .cloned()
        .collect();
    if !bad.is_empty() {
        return Err(format!(
            "{f} must contain qualified Python names{}: {}",
            if wild { " or module.*" } else { "" },
            bad.join(", ")
        ));
    }
    Ok(names.into_iter().collect())
}
fn identifier(s: &str) -> bool {
    let mut c = s.chars();
    c.next().is_some_and(|c| c == '_' || c.is_alphabetic())
        && c.all(|c| c == '_' || c.is_alphanumeric())
}
fn integer(v: &Value, f: &str) -> Result<usize, String> {
    if v.is_null() {
        Ok(0)
    } else {
        v.as_u64()
            .map(|v| v as usize)
            .ok_or_else(|| format!("{f} must be a non-negative integer"))
    }
}
fn default<'a>(v: &'a Value, key: &str, d: &'a Value) -> &'a Value {
    v.get(key).unwrap_or(d)
}
fn policy(raw: &Value, w: &Value, d: &Value) -> Result<Policy, String> {
    let mut custom = BTreeMap::new();
    for (n, v) in table(&raw["layers"], "layers")? {
        let f = format!("layers.{n}");
        if LAYERS.contains(&n.as_str())
            || n.replace(['_', '-'], "").is_empty()
            || !n
                .chars()
                .all(|c| c.is_alphanumeric() || c == '_' || c == '-')
        {
            return Err(format!(
                "{f} must be a new layer name of letters, digits, - and _"
            ));
        }
        keys(v, &["base", "deterministic"], &f)?;
        let base = choice(
            &v["base"],
            &format!("{f}.base"),
            &LAYERS.iter().map(|s| s.to_string()).collect::<Vec<_>>(),
        )?;
        if base == "marker" {
            return Err(format!("{f}.base cannot be marker"));
        }
        let deterministic = v.get("deterministic").map_or(Ok(false), |v| {
            v.as_bool()
                .ok_or_else(|| format!("{f}.deterministic must be true or false"))
        })?;
        custom.insert(
            n.clone(),
            CustomLayer {
                name: n.clone(),
                base,
                deterministic,
            },
        );
    }
    let names: Vec<String> = LAYERS
        .iter()
        .map(|s| s.to_string())
        .chain(custom.keys().cloned())
        .collect();
    let mut maps = Vec::new();
    for key in ["layer_dependencies", "forbidden_imports", "forbidden_calls"] {
        let mut map: BTreeMap<String, BTreeSet<String>> = if d[key].is_null() {
            BTreeMap::new()
        } else {
            serde_json::from_value(d[key].clone()).unwrap()
        };
        let mut explicit = BTreeSet::new();
        for (n, v) in table(&raw[key], key)? {
            choice(&json!(n), &format!("{key} key"), &names)?;
            explicit.insert(n.clone());
            if key == "layer_dependencies" && v == "*" {
                map.remove(n);
                continue;
            }
            let values = if key == "layer_dependencies" {
                strings(v, &format!("{key}.{n}"))?
                    .iter()
                    .map(|s| choice(&json!(s), &format!("{key}.{n}"), &names))
                    .collect::<Result<BTreeSet<_>, _>>()?
            } else {
                qualified(v, &format!("{key}.{n}"), key == "forbidden_calls")?
            };
            map.insert(n.clone(), values);
        }
        let mut ext = BTreeMap::new();
        if key == "forbidden_imports" {
            for (n, v) in table(&raw["extend_forbidden_imports"], "extend_forbidden_imports")? {
                if n != "*" {
                    choice(&json!(n), "extend_forbidden_imports key", &names)?;
                }
                ext.insert(
                    n.clone(),
                    qualified(v, &format!("extend_forbidden_imports.{n}"), false)?,
                );
            }
            for n in names
                .iter()
                .filter(|n| !custom.contains_key(*n) || explicit.contains(*n))
            {
                let extra: BTreeSet<_> = ext
                    .get("*")
                    .into_iter()
                    .flatten()
                    .chain(ext.get(n).into_iter().flatten())
                    .cloned()
                    .collect();
                if !extra.is_empty() {
                    map.entry(n.clone()).or_default().extend(extra);
                }
            }
        }
        for (n, c) in &custom {
            if !explicit.contains(n) {
                if let Some(v) = map.get(&c.base).cloned() {
                    map.insert(n.clone(), v);
                }
                if let Some(v) = ext.get(n) {
                    map.entry(n.clone()).or_default().extend(v.clone());
                }
            }
        }
        maps.push(map);
    }
    let mut allowed = vec![];
    for v in tables(&raw["allowed_dependencies"], "allowed_dependencies")? {
        keys(v, &["modules", "layers", "reason"], "allowed_dependencies")?;
        let modules = qualified(&v["modules"], "allowed_dependencies.modules", true)?;
        if modules.is_empty() {
            return Err("allowed_dependencies.modules must name at least one module".into());
        }
        let layers = list(&v["layers"], "allowed_dependencies.layers")?
            .iter()
            .map(|s| choice(&json!(s), "allowed_dependencies.layers", &names))
            .collect::<Result<_, _>>()?;
        allowed.push(AllowedDependency {
            modules: modules.into_iter().collect(),
            layers,
            reason: string(&v["reason"], "allowed_dependencies.reason")?,
        });
    }
    let c = &raw["conventions"];
    keys(
        c,
        &[
            "predicate_prefixes",
            "outcome_suffixes",
            "allowed_bases",
            "extend_allowed_bases",
        ],
        "conventions",
    )?;
    let mut bases = qualified(
        default(c, "allowed_bases", &d["allowed_bases"]),
        "conventions.allowed_bases",
        true,
    )?;
    bases.extend(qualified(
        &c["extend_allowed_bases"],
        "conventions.extend_allowed_bases",
        true,
    )?);
    let mut domains = BTreeMap::new();
    for (n, v) in table(&raw["domains"], "domains")? {
        if !identifier(n) {
            return Err(format!(
                "domains key must be a Python identifier; got '{n}'"
            ));
        }
        let deps: BTreeSet<_> = strings(v, &format!("domains.{n}"))?.into_iter().collect();
        if deps.contains(n) {
            return Err(format!("domains.{n} cannot depend on itself"));
        }
        domains.insert(n.clone(), deps);
    }
    for (n, deps) in &domains {
        let bad: Vec<_> = deps
            .iter()
            .filter(|s| !domains.contains_key(*s))
            .cloned()
            .collect();
        if !bad.is_empty() {
            return Err(format!(
                "domains.{n} names undeclared domains: {}; give every domain its own entry",
                bad.join(", ")
            ));
        }
    }
    fn visit(
        n: &str,
        g: &BTreeMap<String, BTreeSet<String>>,
        path: &mut Vec<String>,
        done: &mut BTreeSet<String>,
    ) -> Result<(), String> {
        if let Some(i) = path.iter().position(|s| s == n) {
            let mut p = path[i..].to_vec();
            p.push(n.into());
            return Err(format!("domains form a cycle: {}", p.join(" -> ")));
        }
        if done.contains(n) {
            return Ok(());
        }
        path.push(n.into());
        for t in &g[n] {
            visit(t, g, path, done)?
        }
        path.pop();
        done.insert(n.into());
        Ok(())
    }
    let mut done = BTreeSet::new();
    for n in domains.keys() {
        visit(n, &domains, &mut vec![], &mut done)?
    }
    Ok(Policy {
        layer_dependencies: maps.remove(0),
        forbidden_imports: maps.remove(0),
        forbidden_calls: maps.remove(0),
        custom_layers: custom,
        allowed_dependencies: allowed,
        predicate_prefixes: strings(
            default(c, "predicate_prefixes", &d["predicate_prefixes"]),
            "conventions.predicate_prefixes",
        )?,
        outcome_suffixes: strings(
            default(c, "outcome_suffixes", &d["outcome_suffixes"]),
            "conventions.outcome_suffixes",
        )?,
        allowed_bases: bases,
        effectful_types: qualified(&w["effectful_types"], "workspace.effectful_types", false)?,
        clock_modules: qualified(&w["clock_modules"], "workspace.clock_modules", false)?,
        domain_dependencies: domains,
    })
}
const DEFAULTS: &str = r#"{"layer_dependencies": {"core": ["core", "port"], "port": ["core", "port"], "shell": ["core", "port", "shell"], "adapter": ["adapter", "core", "port"], "router": ["boundary", "router", "shell", "transaction"]}, "forbidden_imports": {"core": ["aiohttp", "aiosqlite", "asyncpg", "boto3", "botocore", "fastapi", "httpx", "playwright", "psycopg", "psycopg2", "pydantic", "pydantic_settings", "redis", "requests", "socket", "sqlalchemy", "sqlite3", "starlette", "subprocess"], "port": ["aiohttp", "aiosqlite", "asyncpg", "boto3", "botocore", "fastapi", "httpx", "playwright", "psycopg", "psycopg2", "pydantic", "pydantic_settings", "redis", "requests", "socket", "sqlalchemy", "sqlite3", "starlette", "subprocess"], "shell": ["fastapi", "pydantic", "pydantic_settings", "sqlalchemy", "starlette"], "router": ["sqlalchemy"]}, "predicate_prefixes": ["allows_", "can_", "contains_", "has_", "is_", "matches_", "should_"], "outcome_suffixes": ["AlreadyExists", "Conflict", "Denied", "Expired", "Forbidden", "NotFound", "Rejected", "Unauthorized", "Unavailable"], "allowed_bases": ["builtins.*", "enum.Enum", "enum.Flag", "enum.IntEnum", "enum.IntFlag", "enum.StrEnum", "pydantic.BaseModel", "pydantic.RootModel", "pydantic_settings.BaseSettings", "sqlalchemy.TypeDecorator", "sqlalchemy.ext.declarative.declarative_base", "sqlalchemy.orm.DeclarativeBase", "sqlalchemy.orm.DeclarativeBaseNoMeta", "sqlalchemy.orm.MappedAsDataclass", "sqlalchemy.orm.declarative_base", "sqlalchemy.types.TypeDecorator", "typing.Generic", "typing.NamedTuple", "typing.Protocol", "typing.TypedDict", "typing_extensions.Generic", "typing_extensions.NamedTuple", "typing_extensions.Protocol", "typing_extensions.TypedDict"], "layouts": {"domains": [["src/*/domains/**/boundary.py", "boundary"], ["src/*/domains/**/model.py", "core"], ["src/*/domains/**/core.py", "core"], ["src/*/domains/**/policy.py", "core"], ["src/*/domains/**/event.py", "core"], ["src/*/domains/**/ports.py", "port"], ["src/*/domains/**/service.py", "shell"], ["src/*/domains/*/**/boundary/**/*.py", "boundary"], ["src/*/domains/*/**/model/**/*.py", "core"], ["src/*/domains/*/**/core/**/*.py", "core"], ["src/*/domains/*/**/policy/**/*.py", "core"], ["src/*/domains/*/**/event/**/*.py", "core"], ["src/*/domains/*/**/ports/**/*.py", "port"], ["src/*/domains/*/**/service/**/*.py", "shell"], ["src/*/domains/**/persistence/**/*.py", "adapter"], ["src/*/projections/**/model.py", "core"], ["src/*/projections/**/ports.py", "port"], ["src/*/projections/**/service.py", "shell"], ["src/*/projections/*/**/model/**/*.py", "core"], ["src/*/projections/*/**/ports/**/*.py", "port"], ["src/*/projections/*/**/service/**/*.py", "shell"], ["src/*/projections/**/persistence/**/*.py", "adapter"], ["src/*/shared/model.py", "core"], ["src/*/shared/core.py", "core"], ["src/*/shared/policy.py", "core"], ["src/*/shared/ports.py", "port"], ["src/*/shared/model/**/*.py", "core"], ["src/*/shared/core/**/*.py", "core"], ["src/*/shared/policy/**/*.py", "core"], ["src/*/shared/ports/**/*.py", "port"], ["src/*/shared/persistence/**/*.py", "adapter"], ["src/*/__main__.py", "boundary"], ["src/*/app/**/*.py", "boundary"], ["src/*/app/**/router.py", "router"], ["src/*/app/**/*_router.py", "router"], ["src/*/app/router/**/*.py", "router"], ["src/*/app/routers/**/*.py", "router"], ["src/*/app/dependencies.py", "transaction"], ["src/*/db/**/*.py", "adapter"], ["src/*/db/unit_of_work.py", "transaction"], ["src/*/db/unit_of_work/**/*.py", "transaction"], ["src/*/integrations/**/*.py", "adapter"], ["src/*/integrations/unit_of_work/**/*.py", "transaction"], ["src/*/**/fakes.py", "test"], ["src/*/**/fake.py", "test"], ["src/*/**/fakes/**/*.py", "test"], ["conftest.py", "test"], ["tests/**/*.py", "test"], ["scripts/**/*.py", "boundary"], ["examples/**/*.py", "boundary"], ["migrations/**/*.py", "transaction"]], "hexagonal": [["src/*/*.py", "core"], ["src/*/domain/**/*.py", "core"], ["src/*/domain/**/ports.py", "port"], ["src/*/application/**/*.py", "shell"], ["src/*/application/**/ports.py", "port"], ["src/*/application/**/errors.py", "core"], ["src/*/application/**/*_errors.py", "core"], ["src/*/adapters/**/*.py", "adapter"], ["src/*/adapters/**/database.py", "transaction"], ["src/*/web/**/*.py", "boundary"], ["src/*/app/**/*.py", "boundary"], ["src/*/config.py", "boundary"], ["src/*/development.py", "boundary"], ["src/*/main.py", "boundary"], ["src/*/__main__.py", "boundary"], ["src/*/worker.py", "boundary"], ["conftest.py", "test"], ["tests/**/*.py", "test"], ["scripts/**/*.py", "boundary"], ["examples/**/*.py", "boundary"], ["migrations/**/*.py", "transaction"]], "flat": [["src/**/*.py", "shell"], ["src/*/model.py", "core"], ["src/*/core.py", "core"], ["src/*/policy.py", "core"], ["src/*/ports.py", "port"], ["src/*/model/**/*.py", "core"], ["src/*/core/**/*.py", "core"], ["src/*/policy/**/*.py", "core"], ["src/*/ports/**/*.py", "port"], ["src/*/adapters/**/*.py", "adapter"], ["src/*/cli.py", "boundary"], ["src/*/cli/**/*.py", "boundary"], ["src/*/__main__.py", "boundary"], ["src/*/development.py", "boundary"], ["conftest.py", "test"], ["tests/**/*.py", "test"], ["scripts/**/*.py", "boundary"], ["examples/**/*.py", "boundary"], ["migrations/**/*.py", "transaction"]], "boundary": [["src/**/*.py", "boundary"], ["conftest.py", "test"], ["tests/**/*.py", "test"], ["scripts/**/*.py", "boundary"], ["examples/**/*.py", "boundary"], ["migrations/**/*.py", "transaction"]], "test-support": [["src/**/*.py", "test"], ["conftest.py", "test"], ["tests/**/*.py", "test"], ["scripts/**/*.py", "boundary"], ["examples/**/*.py", "boundary"], ["migrations/**/*.py", "transaction"]]}}"#;
const IGNORED: &[&str] = &[
    ".direnv",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "target",
];
fn cache_imports<'a>(
    nodes: impl IntoIterator<Item = &'a ast::Node>,
    package: Option<&str>,
) -> Vec<CachedImport> {
    let mut result = vec![];
    for node in nodes {
        if ast::kind(node) == "Import" {
            for alias in ast::items(node, "names") {
                result.push((node.clone(), ast::s(alias, "name").into(), None));
            }
        } else if ast::kind(node) == "ImportFrom"
            && let Some(module) = symbols::absolute_module(node, package)
        {
            for alias in ast::items(node, "names") {
                result.push((
                    node.clone(),
                    module.clone(),
                    Some(ast::s(alias, "name").into()),
                ));
            }
        }
    }
    result
}
fn toml_error(error: toml::de::Error, text: &str) -> String {
    if error.message().contains("unclosed table") && error.message().contains("expected `]`") {
        let offset = error
            .span()
            .map_or(text.len(), |span| span.start)
            .min(text.len());
        let before = &text[..offset];
        let line = before.bytes().filter(|b| *b == b'\n').count() + 1;
        let column = before.rsplit('\n').next().unwrap_or("").chars().count() + 1;
        format!("Expected ']' at the end of a table declaration (at line {line}, column {column})")
    } else {
        error.to_string()
    }
}
pub fn find_root(start: &Path) -> PathBuf {
    let start = start.canonicalize().unwrap_or_else(|_| start.to_path_buf());
    for marker in ["lint-it.toml", "pyproject.toml"] {
        for p in start.ancestors() {
            if p.join(marker).is_file() {
                return p.to_path_buf();
            }
        }
    }
    start
}
fn relative(path: &Path, root: &Path) -> String {
    let s = path.strip_prefix(root).unwrap_or(path).to_string_lossy();
    if s.is_empty() {
        ".".into()
    } else {
        s.replace(std::path::MAIN_SEPARATOR, "/")
    }
}
impl Workspace {
    pub fn owner(&self, path: &Path) -> Option<usize> {
        self.packages
            .iter()
            .enumerate()
            .filter(|(_, p)| path.starts_with(&p.root))
            .max_by_key(|(_, p)| p.root.components().count())
            .map(|(i, _)| i)
    }
    pub fn classify(&self, path: &Path) -> Option<Classification> {
        let path = if path.is_absolute() {
            path.to_path_buf()
        } else {
            self.root.join(path)
        };
        let i = self.owner(&path)?;
        let p = &self.packages[i];
        let name = relative(&path, &p.root);
        let ovs: Vec<_> = p
            .overrides
            .iter()
            .filter(|o| matches_glob(&name, st(&o["glob"])))
            .collect();
        if ovs.len() > 1 {
            return None;
        }
        let (glob, layer, origin) = if let Some(o) = ovs.first() {
            (st(&o["glob"]), st(&o["layer"]), "override")
        } else {
            let (g, l) = p
                .layers
                .iter()
                .rev()
                .find(|(g, _)| matches_glob(&name, g))?;
            (g.as_str(), l.as_str(), "layout")
        };
        Some(Classification {
            package: i,
            layer: self.policy.base(layer).into(),
            name: layer.into(),
            origin: origin.into(),
            glob: glob.into(),
        })
    }
    pub(crate) fn top_imports(&self, file: &Source) -> &[CachedImport] {
        self.import_cache[&file.path].top.get_or_init(|| {
            cache_imports(
                ast::items(&file.tree, "body").iter(),
                file.package.as_deref(),
            )
        })
    }
    pub(crate) fn initialization_imports(&self, file: &Source) -> &[(String, Option<String>)] {
        self.import_cache[&file.path]
            .initialization
            .get_or_init(|| {
                let mut pending: Vec<_> = ast::items(&file.tree, "body").iter().collect();
                let mut imports = vec![];
                while let Some(node) = pending.pop() {
                    match ast::kind(node) {
                        "FunctionDef" | "AsyncFunctionDef" | "Lambda" => continue,
                        "Import" | "ImportFrom" => imports.push(node),
                        _ => {
                            if let Some(object) = node.as_object() {
                                for value in object.values() {
                                    if value.get("_type").is_some() {
                                        pending.push(value);
                                    } else if let Some(array) = value.as_array() {
                                        pending.extend(
                                            array.iter().filter(|v| v.get("_type").is_some()),
                                        );
                                    }
                                }
                            }
                        }
                    }
                }
                cache_imports(imports, file.package.as_deref())
                    .into_iter()
                    .map(|(_, module, symbol)| (module, symbol))
                    .collect()
            })
    }
    // Cache only complete traversals: recursive partial results depend on the
    // current cycle guards and cannot safely be shared across imports.
    pub(crate) fn loaded_sources<'a>(
        &'a self,
        module: &str,
        name: Option<&str>,
        compute: impl FnOnce() -> Vec<&'a Source>,
    ) -> Vec<&'a Source> {
        let key = (module.to_owned(), name.map(str::to_owned));
        if let Some(indices) = self.loaded_cache.lock().unwrap().get(&key) {
            return indices.iter().map(|i| &self.sources[*i]).collect();
        }
        let sources = compute();
        let indices = sources
            .iter()
            .map(|s| self.module_index[s.module.as_ref().unwrap()])
            .collect();
        self.loaded_cache.lock().unwrap().insert(key, indices);
        sources
    }
    pub fn module_source(&self, module: &str) -> Option<&Source> {
        self.module_index.get(module).map(|i| &self.sources[*i])
    }
    pub fn dependency_overridden(&self, importer: &Source, imported: &Source) -> bool {
        self.owner(&importer.path).is_some_and(|i| {
            let p = &self.packages[i];
            imported.path.starts_with(&p.root)
                && p.dependency_overrides.iter().any(|o| {
                    st(&o["importer"]) == relative(&importer.path, &p.root)
                        && st(&o["imported"]) == relative(&imported.path, &p.root)
                })
        })
    }
    pub fn configuration_errors(&self) -> Vec<String> {
        let files: Vec<_> = self
            .sources
            .iter()
            .map(|s| &s.path)
            .chain(self.parse_failures.iter().map(|(p, _)| p))
            .collect();
        let mut errors = vec![];
        let mut overridden = BTreeSet::new();
        for (i, p) in self.packages.iter().enumerate() {
            let location = relative(&p.root, &self.root);
            let relative: BTreeMap<_, _> = files
                .iter()
                .filter(|f| self.owner(f) == Some(i))
                .map(|f| (relative(f, &p.root), *f))
                .collect();
            let mut pairs = BTreeSet::new();
            for o in &p.dependency_overrides {
                let a = st(&o["importer"]);
                let b = st(&o["imported"]);
                if !pairs.insert((a, b)) {
                    errors.push(format!(
                        "duplicate dependency override in {location}: {a} -> {b}"
                    ))
                }
                for (role, t) in [("importer", a), ("imported", b)] {
                    if !relative.contains_key(t) {
                        errors.push(format!(
                            "stale dependency override {role} in {location}: {t}"
                        ))
                    }
                }
            }
            for o in &p.overrides {
                let g = st(&o["glob"]);
                let matches: Vec<_> = relative
                    .iter()
                    .filter(|(n, _)| matches_glob(n, g))
                    .map(|(_, p)| *p)
                    .collect();
                if matches.is_empty() {
                    errors.push(format!("stale layout override in {location}: {g}"))
                }
                overridden.extend(matches);
            }
            for name in relative.keys() {
                let globs: Vec<_> = p
                    .overrides
                    .iter()
                    .map(|o| st(&o["glob"]))
                    .filter(|g| matches_glob(name, g))
                    .collect();
                if globs.len() > 1 {
                    errors.push(format!(
                        "overlapping layout overrides for {name}: {}",
                        globs.join(", ")
                    ))
                }
            }
        }
        if overridden.len() > self.override_budget {
            errors.push(format!(
                "layout override budget exceeded: {} files use overrides, budget is {}",
                overridden.len(),
                self.override_budget
            ))
        }
        let modules: Vec<_> = self
            .sources
            .iter()
            .filter_map(|s| s.module.as_deref())
            .collect();
        for a in &self.policy.allowed_dependencies {
            for p in &a.modules {
                if !modules.iter().any(|m| matches_name(m, [p])) {
                    errors.push(format!(
                        "allowed dependency matches no workspace module: {p}"
                    ))
                }
            }
        }
        for n in self.policy.domain_dependencies.keys() {
            if !modules.iter().any(|m| {
                let p: Vec<_> = m.split('.').collect();
                p.len() > 2 && p[1] == "domains" && p[2] == n
            }) {
                errors.push(format!("declared domain matches no domains/ package: {n}"))
            }
        }
        let count: usize = self
            .packages
            .iter()
            .map(|p| p.dependency_overrides.len())
            .sum();
        if count > self.dependency_override_budget {
            errors.push(format!(
                "dependency override budget exceeded: {count} edges use overrides, budget is {}",
                self.dependency_override_budget
            ))
        }
        errors.sort();
        errors
    }
}
pub fn load(root: &Path) -> Result<Workspace, String> {
    let _span = crate::profile::span("workspace_load");
    let root = root.canonicalize().map_err(|e| e.to_string())?;
    let manifest = root.join("lint-it.toml");
    let raw: Value = if manifest.is_file() {
        let text = std::fs::read_to_string(&manifest).map_err(|e| e.to_string())?;
        let v: toml::Value = toml::from_str(&text).map_err(|e| toml_error(e, &text))?;
        serde_json::to_value(v).map_err(|e| e.to_string())?
    } else {
        json!({})
    };
    keys(
        &raw,
        &[
            "workspace",
            "packages",
            "layers",
            "layouts",
            "layer_dependencies",
            "forbidden_imports",
            "extend_forbidden_imports",
            "forbidden_calls",
            "allowed_dependencies",
            "ignore",
            "conventions",
            "overrides",
            "dependency_overrides",
            "domains",
        ],
        "manifest",
    )?;
    let w = &raw["workspace"];
    keys(
        w,
        &[
            "kind",
            "layout",
            "effectful_types",
            "clock_modules",
            "override_budget",
            "dependency_override_budget",
            "baseline",
        ],
        "workspace",
    )?;
    let mut projects = BTreeSet::new();
    let mut paths = BTreeSet::new();
    for entry in walkdir::WalkDir::new(&root).into_iter().filter_entry(|e| {
        e.depth() == 0 || !IGNORED.contains(&e.file_name().to_string_lossy().as_ref())
    }) {
        let e = entry.map_err(|e| e.to_string())?;
        if e.file_type().is_file() {
            if e.file_name() == "pyproject.toml" {
                projects.insert(
                    e.path()
                        .parent()
                        .unwrap()
                        .canonicalize()
                        .map_err(|e| e.to_string())?,
                );
            }
            if e.path().extension().is_some_and(|s| s == "py") {
                paths.insert(e.path().canonicalize().map_err(|e| e.to_string())?);
            }
        }
    }
    if projects.is_empty() {
        return Err(format!("no pyproject.toml found under {}", root.display()));
    }
    let d: Value = serde_json::from_str(DEFAULTS).unwrap();
    let policy = policy(&raw, w, &d)?;
    let names: Vec<String> = LAYERS
        .iter()
        .map(|s| s.to_string())
        .chain(policy.custom_layers.keys().cloned())
        .collect();
    let mut layouts: BTreeMap<String, Vec<(String, String)>> =
        serde_json::from_value(d["layouts"].clone()).unwrap();
    let builtin = vec![
        "domains".into(),
        "hexagonal".into(),
        "flat".into(),
        "boundary".into(),
        "test-support".into(),
    ];
    let conventions = vec![
        ("conftest.py".into(), "test".into()),
        ("tests/**/*.py".into(), "test".into()),
        ("scripts/**/*.py".into(), "boundary".into()),
        ("examples/**/*.py".into(), "boundary".into()),
        ("migrations/**/*.py".into(), "transaction".into()),
    ];
    let mut layout_names = builtin.clone();
    for (n, v) in table(&raw["layouts"], "layouts")? {
        if layouts.contains_key(n) || !v.is_object() {
            return Err(format!(
                "layout {n} must be a table and cannot redefine a built-in"
            ));
        }
        keys(v, &["extends", "layers"], &format!("layouts.{n}"))?;
        let mut pats = if let Some(x) = v.get("extends") {
            let p = choice(x, &format!("layouts.{n}.extends"), &builtin)?;
            layouts[&p].clone()
        } else {
            conventions.clone()
        };
        let entries = v["layers"]
            .as_array()
            .filter(|a| !a.is_empty())
            .ok_or_else(|| format!("layouts.{n}.layers must be a non-empty array"))?;
        for e in entries {
            let f = format!("layouts.{n}.layers");
            if !e.is_object() {
                return Err(format!("{f} entries must be tables"));
            }
            keys(e, &["glob", "layer"], &f)?;
            pats.push((
                pyglob(&e["glob"], &format!("{f}.glob"))?,
                choice(&e["layer"], &format!("{f}.layer"), &names)?,
            ));
        }
        layouts.insert(n.clone(), pats);
        layout_names.push(n.clone());
    }
    for pats in layouts.values_mut() {
        pats.push(("src/**/__init__.py".into(), "marker".into()));
    }
    let kinds = vec!["server".into(), "client".into(), "library".into()];
    let dk = choice(
        default(w, "kind", &json!("server")),
        "workspace.kind",
        &kinds,
    )?;
    let dl = choice(
        default(w, "layout", &json!("domains")),
        "workspace.layout",
        &layout_names,
    )?;
    let mut configured = BTreeMap::new();
    for e in tables(&raw["packages"], "packages")? {
        keys(e, &["path", "kind", "layout"], "packages")?;
        let p = root.join(rel(&e["path"], "packages.path")?);
        if configured.contains_key(&p) {
            return Err(format!("duplicate package entry: {}", relative(&p, &root)));
        }
        if !projects.contains(&p) {
            return Err(format!(
                "package has no pyproject.toml: {}",
                relative(&p, &root)
            ));
        }
        configured.insert(
            p,
            (
                choice(default(e, "kind", &json!(dk)), "packages.kind", &kinds)?,
                choice(
                    default(e, "layout", &json!(dl)),
                    "packages.layout",
                    &layout_names,
                )?,
            ),
        );
    }
    let mut overrides: BTreeMap<PathBuf, Vec<Value>> = BTreeMap::new();
    let mut deps: BTreeMap<PathBuf, Vec<Value>> = BTreeMap::new();
    for (key, map) in [
        ("overrides", &mut overrides),
        ("dependency_overrides", &mut deps),
    ] {
        for e in tables(&raw[key], key)? {
            keys(
                e,
                if key == "overrides" {
                    &["package", "glob", "layer", "reason", "issue"]
                } else {
                    &["package", "importer", "imported", "reason", "issue"]
                },
                key,
            )?;
            let p = root.join(rel(
                default(e, "package", &json!(".")),
                &format!("{key}.package"),
            )?);
            if !projects.contains(&p) {
                return Err(format!(
                    "{key}.package has no pyproject.toml: {}",
                    relative(&p, &root)
                ));
            }
            let mut e = e.clone();
            if key == "overrides" {
                let g = pyglob(&e["glob"], "override.glob")?;
                if let Some(i) = g.find(['*', '?', '['])
                    && g[..i]
                        .trim_end_matches('/')
                        .split('/')
                        .filter(|s| !s.is_empty())
                        .count()
                        < 3
                {
                    return Err(format!(
                        "override.glob is too broad; scope it below a package area: {g}"
                    ));
                }
                e["glob"] = json!(g);
                e["layer"] = json!(choice(&e["layer"], "overrides.layer", &names)?);
            } else {
                for f in ["importer", "imported"] {
                    e[f] = json!(pyglob(&e[f], &format!("{key}.{f}"))?);
                }
            }
            for f in ["reason", "issue"] {
                e[f] = json!(string(&e[f], &format!("{key}.{f}"))?);
            }
            map.entry(p).or_default().push(e);
        }
    }
    let packages = projects
        .into_iter()
        .map(|p| {
            let (k, l) = configured.remove(&p).unwrap_or((dk.clone(), dl.clone()));
            Package {
                layers: layouts[&l].clone(),
                kind: k,
                layout: l,
                overrides: overrides.remove(&p).unwrap_or_default(),
                dependency_overrides: deps.remove(&p).unwrap_or_default(),
                root: p,
            }
        })
        .collect();
    let mut ignores = vec![];
    for e in tables(&raw["ignore"], "ignore")? {
        keys(e, &["rules", "paths", "layers", "reason"], "ignore")?;
        let rules = strings(&e["rules"], "ignore.rules")?;
        if rules.is_empty() {
            return Err("ignore.rules must name at least one rule".into());
        }
        ignores.push(Ignore {
            rules,
            paths: list(&e["paths"], "ignore.paths")?
                .iter()
                .map(|s| rel(&json!(s), "ignore.paths"))
                .collect::<Result<_, _>>()?,
            layers: list(&e["layers"], "ignore.layers")?
                .iter()
                .map(|s| choice(&json!(s), "ignore.layers", &names))
                .collect::<Result<_, _>>()?,
            reason: string(&e["reason"], "ignore.reason")?,
        });
    }
    let baseline_path = w
        .get("baseline")
        .map(|v| rel(v, "workspace.baseline").map(|s| root.join(s)))
        .transpose()?;
    let mut baseline = BTreeMap::new();
    if let Some(p) = baseline_path.as_ref().filter(|p| p.is_file()) {
        let text = std::fs::read_to_string(p).map_err(|e| e.to_string())?;
        let b: Value = serde_json::from_str(&text).map_err(|e| baseline_json_error(&text, e))?;
        if !b.is_object() || b["version"] != 1 {
            return Err("baseline must be an object with version 1".into());
        }
        let files = b["findings"]
            .as_object()
            .ok_or("baseline findings must be an object keyed by file")?;
        for (f, entries) in files {
            for e in entries
                .as_array()
                .ok_or_else(|| format!("baseline entries for {f} must be an array"))?
            {
                let count = e
                    .get("count")
                    .map_or(Some(1), Value::as_u64)
                    .filter(|c| *c > 0);
                if !e["code"].is_string() || !e["message"].is_string() || count.is_none() {
                    return Err(format!(
                        "baseline entry for {f} needs code, message and count"
                    ));
                }
                *baseline
                    .entry((f.clone(), st(&e["code"]).into(), st(&e["message"]).into()))
                    .or_insert(0) += count.unwrap() as usize;
            }
        }
    }
    let mut ws = Workspace {
        module_index: HashMap::new(),
        loaded_cache: Mutex::new(HashMap::new()),
        import_cache: HashMap::new(),
        root,
        manifest: manifest.is_file().then_some(manifest),
        packages,
        sources: vec![],
        parse_failures: vec![],
        policy,
        ignores,
        baseline_path,
        baseline,
        override_budget: integer(&w["override_budget"], "workspace.override_budget")?,
        dependency_override_budget: integer(
            &w["dependency_override_budget"],
            "workspace.dependency_override_budget",
        )?,
    };
    let paths: Vec<_> = paths
        .into_iter()
        .filter(|p| ws.owner(p).is_some())
        .collect();
    // The indexed parallel iterator preserves path order while resolving each
    // file's symbols on the same worker as its parse.
    let parsed: Vec<_> = paths
        .par_iter()
        .map(|path| {
            let src = std::fs::read_to_string(path).map_err(|e| e.to_string())?;
            let tree = match ast::parse(&src) {
                Ok(tree) => tree,
                Err(error) => return Ok(Err((path.clone(), error))),
            };
            let owner = ws.owner(path).unwrap();
            let module = path
                .strip_prefix(ws.packages[owner].root.join("src"))
                .ok()
                .map(|p| {
                    let mut s = p
                        .with_extension("")
                        .to_string_lossy()
                        .replace(std::path::MAIN_SEPARATOR, ".");
                    if s == "__init__" {
                        s.clear()
                    } else if s.ends_with(".__init__") {
                        s.truncate(s.len() - 9);
                    }
                    s
                });
            let package = module.as_ref().map(|m| {
                if path.file_name().is_some_and(|s| s == "__init__.py") {
                    m.clone()
                } else {
                    m.rsplit_once('.').map_or("", |(p, _)| p).into()
                }
            });
            let symbols = symbols::resolve(&tree, package.as_deref());
            Ok(Ok(Source {
                filename: relative(path, &ws.root),
                classification: ws.classify(path),
                path: path.clone(),
                tree,
                module,
                package,
                symbols,
            }))
        })
        .collect::<Result<_, String>>()?;
    for result in parsed {
        match result {
            Ok(source) => ws.sources.push(source),
            Err(failure) => ws.parse_failures.push(failure),
        }
    }
    ws.module_index = ws
        .sources
        .iter()
        .enumerate()
        .filter_map(|(i, s)| s.module.clone().map(|m| (m, i)))
        .collect();
    ws.import_cache = ws
        .sources
        .iter()
        .map(|source| (source.path.clone(), SourceImports::default()))
        .collect();
    Ok(ws)
}

fn baseline_json_error(text: &str, error: serde_json::Error) -> String {
    let message = error.to_string();
    if message.starts_with("EOF while parsing an object")
        || message.starts_with("key must be a string")
    {
        let offset = if error.is_eof() {
            text.len()
        } else {
            text.split_inclusive('\n')
                .take(error.line().saturating_sub(1))
                .map(str::len)
                .sum::<usize>()
                + error.column().saturating_sub(1)
        };
        let before = &text[..offset.min(text.len())];
        let line = before.bytes().filter(|b| *b == b'\n').count() + 1;
        let column = before.rsplit('\n').next().unwrap_or("").chars().count() + 1;
        return format!(
            "baseline is not valid JSON: Expecting property name enclosed in double quotes: line {line} column {column} (char {})",
            before.chars().count()
        );
    }
    format!("baseline is not valid JSON: {error}")
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn glob_segments_and_recursive_zero_depth() {
        assert!(matches_glob("src/app/core.py", "src/**/core.py"));
        assert!(matches_glob("core.py", "**/core.py"));
        assert!(!matches_glob("src/app/deep/core.py", "src/*/core.py"));
        assert!(matches_glob("tests/test_a.py", "tests/test_[a-z].py"));
        assert!(!matches_glob("tests/test_a.py", "tests/test_[!a-z].py"));
    }
    #[test]
    fn unclosed_toml_table_matches_python_diagnostic() {
        let text = "[workspace\n";
        let error = toml::from_str::<toml::Value>(text).unwrap_err();
        assert_eq!(
            toml_error(error, text),
            "Expected ']' at the end of a table declaration (at line 1, column 11)"
        );
    }
    #[test]
    fn native_workspace_classification_and_policy() {
        let root =
            std::env::temp_dir().join(format!("lint-it-native-workspace-{}", std::process::id()));
        std::fs::create_dir_all(root.join("src/example/domains/orders")).unwrap();
        std::fs::write(root.join("pyproject.toml"), "[project]\nname='example'\n").unwrap();
        std::fs::write(
            root.join("src/example/domains/orders/core.py"),
            "import httpx\n",
        )
        .unwrap();
        std::fs::write(root.join("src/example/__init__.py"), "").unwrap();
        let ws = load(&root).unwrap();
        assert_eq!(ws.sources.len(), 2);
        assert_eq!(
            ws.classify(Path::new("src/example/domains/orders/core.py"))
                .unwrap()
                .layer,
            "core"
        );
        assert_eq!(
            ws.classify(Path::new("src/example/__init__.py"))
                .unwrap()
                .layer,
            "marker"
        );
        assert!(ws.policy.forbidden_imports["core"].contains("httpx"));
        assert!(ws.module_source("example.domains.orders.core").is_some());
        assert!(ws.configuration_errors().is_empty());
        assert!(
            ws.sources
                .windows(2)
                .all(|pair| pair[0].path < pair[1].path)
        );
        let core = ws.module_source("example.domains.orders.core").unwrap();
        assert_eq!(core.filename, "src/example/domains/orders/core.py");
        assert_eq!(core.package.as_deref(), Some("example.domains.orders"));
        let top = ws.top_imports(core);
        assert_eq!(top[0].1, "httpx");
        assert!(std::ptr::eq(top, ws.top_imports(core)));
        let initialization = ws.initialization_imports(core);
        assert_eq!(initialization, &[("httpx".into(), None)]);
        assert!(std::ptr::eq(
            initialization,
            ws.initialization_imports(core)
        ));
        let findings = crate::dependencies::check(
            ws.module_source("example.domains.orders.core").unwrap(),
            &ws,
        );
        assert_eq!(findings.len(), 1);
        assert_eq!(findings[0].code, "LIT102");
        std::fs::remove_dir_all(root).unwrap();
    }
}
