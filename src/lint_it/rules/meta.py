from __future__ import annotations

from collections.abc import Iterable

from lint_it.core import Finding, SourceFile, finding


class ParseErrorRule:
    """A Python file in the workspace cannot be parsed.

    No other rule can check a file that does not parse, so this finding hides
    nothing: fix the syntax error and run the check again.
    """

    code = "LIT001"
    name = "parse-error"

    def check(self, file: SourceFile) -> Iterable[Finding]:
        return ()


class UnclassifiedFileRule:
    """A Python file matches no layer.

    Every file in a package must belong to exactly one layer, because the other
    rules are defined per layer. Move the file to a path the package layout
    recognizes, extend the layout in `[layouts.<name>]`, or add an `[[overrides]]`
    entry with a reason and an issue.
    """

    code = "LIT002"
    name = "unclassified-file"

    def check(self, file: SourceFile) -> Iterable[Finding]:
        if file.classification is not None:
            return ()
        message = "file matches no layer in its package layout"
        package = file.workspace.package_for(file.path)
        if package is not None:
            message += f" ({package.layout}); move it, extend the layout, or add an override"
        return (finding(self, file, file.tree, message),)


class ManifestRule:
    """`lint-it.toml` is invalid or out of date with the workspace.

    Reported at `lint-it.toml:1` for schema errors, unknown keys, overrides that
    no longer match any file, overlapping overrides, and exceeded override
    budgets. A manifest that cannot be loaded at all exits with status 2.
    """

    code = "LIT003"
    name = "manifest"

    def check(self, file: SourceFile) -> Iterable[Finding]:
        return ()
