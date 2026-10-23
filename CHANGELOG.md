# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/). Public contracts: the model schema
`schema_version` and the `dist/` TextMate scope names.

## [Unreleased]

### Added
- The PlantUML command model (`model/`, `schema_version` 1): models generated from the
  upstream sources at `97a5992` (`1.2026.8beta1`) by the Java extractor and the translator,
  refined by hand per diagram family, each rule citing its upstream `file:line`.
- The interpreter (`tools/interp`): ordered first-match command matching over a context
  stack, with Java regex semantics (`tools/model/java_regex.py`), as PlantUML runs its
  command factories.
- The TextMate grammar `dist/plantuml.tmLanguage.json` (`source.plantuml`), generated from
  the model and proved with `vscode-textmate`.
- The parity harness (`tools/validate`): every `@start...@end` block of the vega,
  plantuml-ts and pdiff corpora through the PlantUML jar and the interpreter, with every
  false accept or reject classified (`reports/classify/`).
