use crate::{ast::Node, symbols::Symbols, workspace::Workspace};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub struct Finding {
    pub filename: String,
    pub line: usize,
    pub column: usize,
    pub code: String,
    pub message: String,
    pub target: Option<String>,
}
#[derive(Debug, Clone)]
pub struct ParseFailure {
    pub line: usize,
    pub column: usize,
    pub message: String,
}
#[derive(Debug, Clone)]
pub struct Classification {
    pub package: usize,
    pub layer: String,
    pub name: String,
    pub origin: String,
    pub glob: String,
}
#[derive(Debug, Clone)]
pub struct Source {
    pub path: PathBuf,
    pub filename: String,
    pub tree: Node,
    pub module: Option<String>,
    pub package: Option<String>,
    pub classification: Option<Classification>,
    pub symbols: Symbols,
}
impl Source {
    pub fn layer(&self) -> &str {
        self.classification
            .as_ref()
            .map_or("", |c| c.layer.as_str())
    }
    pub fn layer_name(&self) -> &str {
        self.classification.as_ref().map_or("", |c| c.name.as_str())
    }
    pub fn has_layer(&self, layers: &[&str]) -> bool {
        layers.contains(&self.layer())
    }
    pub fn deterministic(&self, w: &Workspace) -> bool {
        w.policy
            .custom_layers
            .get(self.layer_name())
            .is_some_and(|c| c.deterministic)
    }
}
pub fn finding(
    file: &Source,
    node: &Node,
    code: &str,
    message: impl Into<String>,
    target: Option<String>,
) -> Finding {
    Finding {
        filename: file.filename.clone(),
        line: node["lineno"].as_u64().unwrap_or(1) as usize,
        column: node["col_offset"].as_u64().unwrap_or(0) as usize,
        code: code.into(),
        message: message.into(),
        target,
    }
}
pub fn relative_name(path: &std::path::Path, root: &std::path::Path) -> String {
    path.strip_prefix(root)
        .unwrap_or(path)
        .to_string_lossy()
        .replace('\\', "/")
}
