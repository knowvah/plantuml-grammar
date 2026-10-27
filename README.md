# plantuml-grammar
The syntax of the PlantUML language as a command model extracted from the upstream sources,
an interpreter that parses with it, a TypeScript port of that interpreter, and a TextMate
grammar generated from it.

**Status:** pre-release, built against PlantUML `97a5992` (`1.2026.8beta1`). See
[CHANGELOG](CHANGELOG.md).

## Purpose
PlantUML has no grammar of its own: its syntax is the ordered list of regular expressions in
each diagram factory's `Command` classes, tried first match first, with state carried from
line to line. This repository keeps that syntax as one YAML *command model* and runs it the
same way:

- `model/` - the command model, generated from the upstream sources and refined by hand,
  every rule citing its upstream `file:line`
- `tools/interp` - an interpreter of the model: ordered first-match command matching over a
  context stack, as PlantUML does it
- `dist/plantuml.tmLanguage.json` - a TextMate grammar generated from the model (Oniguruma
  and PCRE compatible)
- `packages/engine` and `dist/plantuml.engine.json` - the TypeScript engine and the model it
  runs

Correctness is measured against the real PlantUML jar: every `@start...@end` block of three
corpora is run through the jar and through the interpreter, and every disagreement is
classified.

**Engine.** `packages/engine` is a TypeScript port of the interpreter. It runs the model
from `dist/plantuml.engine.json` (`engine_format` 1), where every regex is already
translated from Java to ES2018 JavaScript (flag `u`, no modifiers), so it runs in browsers,
VS Code and JetBrains JCEF 122+. Its verdicts equal the
Python interpreter's on every conformance golden and every corpus block (accepted, diagram,
model, status and first failure). The core has no Node dependency; a JSONL CLI with a
killable worker pool serves the parity harness.

## Install
The grammar and the engine are published together as
[`@knowvah/plantuml-grammar`](packages/engine/README.md):

```sh
npm install @knowvah/plantuml-grammar
```

It exports the engine API and the files `plantuml.tmLanguage.json` and
`plantuml.engine.json`. Releases are cut from Conventional Commits on `main`; see
[PUBLISHING.md](PUBLISHING.md).

## Layout
| Path | Content |
|---|---|
| `model/` | Hand-written model (`document`, `preproc`, `shared`, `creole`, `diagrams/`, `embedded/`) and `schema.json`. |
| `model/generated/` | Models generated from the upstream sources. Never edit by hand. |
| `extracted/` | Raw command regex trees dumped from the jar by the Java extractor. |
| `dist/` | Generated artifacts, committed and reproducible from `model/`: the TextMate grammar and `plantuml.engine.json`, the engine model with JavaScript regexes. |
| `packages/engine/` | The TypeScript engine and the npm package `@knowvah/plantuml-grammar` (npm workspace): browser-safe core (`src/`), JSONL CLI and worker pool (`cli.ts`, `pool.ts`, `worker.ts`), vitest suite. |
| `tools/` | Python tooling: `extract`, `translate`, `model` (loader), `interp`, `emit`, `validate`, `report`; Java harness in `tools/extract` and `tools/oracle`. |
| `reports/` | Parity reports per corpus (`parity-*.json`, `.md`, slices in `parity/`), the TS lane (`parity-*-ts.*`, slices in `parity-ts/`), Python/TS equality (`engine-equality-*`) and classifications (`classify/`). |
| `docs/` | [Grammar guide](docs/grammar-guide.md), [command coverage](docs/coverage.md), [semantic gaps](docs/semantic-gaps.md). |
| `tests/` | pytest suite, conformance goldens (`tests/conformance`) and the `vscode-textmate` proof (`tests/textmate`). |

## Prerequisites
- `uv` (Python 3.11+, dependencies in `pyproject.toml`), Node 26 and npm (pinned through Volta in
  `package.json`), Java 21 (`javac`, `java`).
- To regenerate or run parity (not needed to use `dist/`): the PlantUML jar built from the pinned
  commit, a PlantUML checkout containing it, and the corpora. Defaults, overridable by
  environment variable:

  | Variable | Default |
  |---|---|
  | `PLANTUML_JAR` | `~/git/knowvah/plantuml-ts/oracle/dist/stock/plantuml-stock-97a5992201a7b1bc5d4063a81da609fe7387fede.jar` |
  | `PLANTUML_SRC` | `~/git/plantuml` |
  | `CORPUS_VEGA` | `$PLANTUML_SRC/src/test/resources/vega` |
  | `CORPUS_PLANTUML_TS` | `~/git/knowvah/plantuml-ts/tests/corpus` |
  | `CORPUS_PDIFF` | `~/git/pdiff` |

  The jar and corpora are not part of this repository.

## Regenerate
Setup once: `uv sync && npm ci`.

```sh
uv run python -m tools.emit.build        # model/ -> dist/ (TextMate grammar, engine JSON; no jar needed)
uv run python -m tools.validate.conformance   # tests/conformance goldens from the Python interpreter
```

After an upstream bump or a change to the extractor, the full chain is
`tools.extract.build`, `tools.extract.run`, `tools.translate.run`, `tools.model.load --check
model/`, `tools.emit.build`, parity; see "Regenerating after an upstream bump" in the
[grammar guide](docs/grammar-guide.md).

```sh
uv run python -m tools.report.coverage        # docs/coverage.md
uv run python -m tools.validate.parity --corpus all --workers 4
uv run python -m tools.validate.parity merge --corpus all
uv run python -m tools.report.semantic_gaps   # docs/semantic-gaps.md
```

The TS lane runs the same jobs through the TypeScript engine as well and writes the
`-ts` and equality reports (it builds `packages/engine` when `src/` is newer):

```sh
uv run python -m tools.validate.parity --corpus all --workers 4 --engine both
uv run python -m tools.validate.parity merge --corpus all --engine both
```

## Validate
These five gates must pass (`npm test` runs the TextMate proof and the engine suite: tsc,
vitest with 90% coverage, and the conformance test against the Python goldens):

```sh
uv run pytest --cov=tools --cov-branch --cov-fail-under=90
uv run ruff check . && uv run ruff format --check .
npm test
uv run python -m tools.model.load --check model/
uv run python -m tools.extract.build
```

Without the jar and corpora, run `uv run pytest -m "not corpus"` for the tests that need no
external input. pytest runs on four workers (`pytest-xdist`, set in `pyproject.toml`); the
model is loaded once per worker (`tests/helpers/models.py`). Pass `-n 0` for a serial run.

CI (`.github/workflows/ci.yml`) runs everything that needs no jar on each pull request and
push to `main`: ruff, pyright on `tools/emit`, `tools/report` and `tools/validate`,
`load --check`, a rebuild of `dist/` that must match the committed files,
`pytest -m "not corpus"` and `npm test`. The corpus tests, `tools.extract.build` and parity
still run locally. `release.yml` publishes the npm package from `main`
([PUBLISHING.md](PUBLISHING.md)).

## Status
Command coverage (`docs/coverage.md`): 1,245 extracted commands: 1,228 modeled, 2 partial
(the opaque `@startyaml` and `@starthcl` bodies), 15 excluded with a reason, 0 missing. Egg
(XOR-decoded, not regular) is excluded.

Parity of the interpreter with the jar, per corpus:

| Corpus | Blocks | FR | FA |
|---|---|---|---|
| vega | 301 | 0 | 0 |
| plantuml-ts | 4401 | 0 | 32 |
| pdiff | 5834 | 0 | 47 |

FR = jar accepts, model rejects. FA = jar rejects, model accepts; every FA is classified
`semantic` (upstream checks that need state or lookups across lines, listed in
[semantic gaps](docs/semantic-gaps.md)). Test suite: 4,319 tests pass (12 skipped, 148 expected failures that pin known
gaps), 98.8% line and branch coverage of `tools/` (gate: 90%).

TS lane: the same jobs judged by the TypeScript engine (`--engine both`):

| Corpus | Blocks | Python/TS mismatches | FR | FA |
|---|---|---|---|---|
| vega | 301 | 0 | 0 | 0 |
| plantuml-ts | 4401 | 0 | 0 | 32 |
| pdiff | 5834 | 0 | 0 | 47 |

The engine also matches all 3,672 conformance goldens (3,370 fixture cases, 302 toy cases),
in a suite of 478 vitest tests. `dist/plantuml.engine.json` is 3.8 MB (118 KB gzip; 788
patterns, 247 contexts, none unsupported). Loading it takes about 15 ms; V8 compiles each
regex on its first execution, large patterns sit behind small guards and three recursive
leaves are parsed natively, so the first verdict in a fresh process takes under 45 ms for
most diagram families and 100-240 ms for the UML ones (`npm run bench -w packages/engine`).
Judge wall time per corpus with 4 workers, Python vs TS: vega 14.0 s vs 1.8 s, plantuml-ts
19.5 s vs 4.7 s, pdiff 21.9 s vs 10.6 s.

Details: [grammar guide](docs/grammar-guide.md) (model format, regeneration, troubleshooting),
[command coverage](docs/coverage.md), [semantic gaps](docs/semantic-gaps.md),
[CHANGELOG](CHANGELOG.md). Known limits of the TextMate grammar are listed in the guide,
section "Generated grammars".

## License
This project is licensed under the [MIT License](LICENSE).
