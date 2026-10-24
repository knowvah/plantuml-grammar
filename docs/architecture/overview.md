# Architecture overview

Snapshot 2026-10-23. Covers plantuml-grammar and the two knowvah repositories it is coupled
to: plantuml-ts and plantuml-plugins.

## Index
- [inventory.md](inventory.md): one row per repo, plus component summaries
- [architecture.md](architecture.md): system diagram across the three repos
- [components.md](components.md): internal structure of each repo
- [data-flow.md](data-flow.md): sequence diagrams for the key flows
- [tech-health.md](tech-health.md): runtime EOL dates and known CVEs

## What the system does
PlantUML has no formal grammar. Its syntax is the ordered list of regexes in each diagram
factory's `Command` classes, tried first-match-first, with state carried from line to line.
**plantuml-grammar** turns that syntax into data:

1. It extracts the regexes from the pinned upstream jar (PlantUML `97a5992`, `1.2026.8beta1`).
2. It translates them into a YAML command model. Every rule cites its upstream `file:line`.
3. It runs the model with an interpreter that mirrors PlantUML's command loop.
4. It generates a TextMate grammar, `dist/plantuml.tmLanguage.json`, from the model.

Correctness is measured against the real jar on three corpora (vega 301 blocks, plantuml-ts
4,401, pdiff 5,834). The current result is FR = 0 on all three. FA is 32 on plantuml-ts and
47 on pdiff, and every FA is classified `semantic`.

The planned next step is a TypeScript engine: the model as JSON, with the regexes translated
from Java to JavaScript, and a TS port of `tools/interp`. It would serve as a parser and as
the source of semantic highlighting.

## How the repos relate
| From | To | Kind of coupling | Status |
|---|---|---|---|
| plantuml-grammar | plantuml-ts `oracle/dist/stock/plantuml-stock-<sha>.jar` | Default `PLANTUML_JAR`, used to extract commands and as the parity oracle | Active; filesystem path, not a package dependency |
| plantuml-grammar | plantuml-ts `tests/corpus` | Default `CORPUS_PLANTUML_TS`, a parity corpus | Active; filesystem path |
| plantuml-plugins | plantuml-ts | `link:` dependency of `@knowvah/plantuml-core` (engine is unpublished) | Active. The link target is `~/git/plantuml-ts`, which does not exist on this machine (see [tech-health.md](tech-health.md#findings)) |
| plantuml-ts docs-site | plantuml-plugins `packages/vscode/syntaxes/plantuml.tmLanguage.json` | Hand copy of the TextMate grammar into `docs-site/.vitepress/plantuml.tmLanguage.ts` | Active; manual copy |
| plantuml-grammar `dist/plantuml.tmLanguage.json` | plantuml-plugins VS Code extension, plantuml-ts docs-site | Prospective replacement for the 110-line hand grammar. The scope name `source.plantuml` already matches. | Not wired. Neither repo references plantuml-grammar. npm packaging is plantuml-grammar issue #1. |
| plantuml-ts | `@knowvah/dot-engine` (org repo `dot-engine`) | npm dependency, version 2.4.0 | Not analyzed here; it is two hops from plantuml-grammar |

There are no network services, databases or queues anywhere in the three repos. Every
coupling is either a filesystem path or an npm package. The only processes that start
other processes are plantuml-grammar's JVM and `git show` calls and plantuml-plugins'
render worker.

## Key data flows
1. **Upstream bump.** Extract (Java, jar) produces `extracted/*.json`. Translate produces
   `model/generated/*.yaml`. Then `model.load --check` runs, followed by coverage, emit and
   parity. See [data-flow.md](data-flow.md#1-upstream-bump-regenerate-the-model).
2. **Parity validation.** The corpora go to the Java Oracle (verdicts cached in
   `reports/oracle-cache`) and to the interpreter (a process pool). The two verdicts are
   compared, FR and FA cases are classified with `reports/classify/*.yaml`, and the results
   are written to `reports/parity-*`. See [data-flow.md](data-flow.md#2-parity-validation-against-the-jar).
3. **Highlighting.** `model/` goes to `tools.emit.build`, which writes
   `dist/plantuml.tmLanguage.json`. The editors (VS Code, Shiki) are intended consumers;
   today they use the hand grammar. See [data-flow.md](data-flow.md#3-highlighting-and-rendering-a-plantuml-file-in-vs-code).

## Tech stack summary
| Repo | Language | Runtime | Framework | Database | External deps |
|---|---|---|---|---|---|
| plantuml-grammar | Python, Java, JS (tests) | Python >=3.11, Java 21, Node | — (pytest, ruff, uv) | — | PlantUML jar and source checkout, three corpora, pyyaml, jsonschema, regex, vscode-textmate |
| plantuml-ts | TypeScript | Node >=26 | VitePress 1.6.4 (docs), Vite 8 | — | @knowvah/dot-engine, elkjs, katex, pako, @xmldom/xmldom; external PlantUML fork for the oracle |
| plantuml-plugins | TypeScript, Kotlin | Node >=22, VS Code ^1.125, JetBrains 2025.2 | VitePress, Eleventy, Docusaurus, React, markdown-it plugins | — | @knowvah/plantuml-ts (link:), markdown-it, unist-util-visit |
