# Changelog

## 0.9.1

- First standalone public release, extracted from the existing 0.9.0 package.
- Preserve all 24 PAL rules, advisory checks, package checks, and CLI entry points.
- Add standalone development configuration, CI, and GitHub installation instructions.
- Make the repository coverage test independent of its former host workspace.
- Add an explicit AST class-map type annotation for current type checkers;
  rule behavior is unchanged.

## 0.9.0

Previously distributed through a private package index. Introduced project-owned
layout profiles, package dependency policies, and PAL024 service boundary checks.
