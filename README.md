# plantuml-grammar
The syntax of the PlantUML language as a command model extracted from the upstream sources,
an interpreter that parses with it, and a TextMate grammar generated from it.

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

Correctness is measured against the real PlantUML jar: every `@start...@end` block of three
corpora is run through the jar and through the interpreter, and every disagreement is
classified.

Next: a TypeScript engine (the model as JSON with the regexes translated to JavaScript, and a
port of the interpreter), usable as a parser and as the source of semantic highlighting.

## Layout
| Path | Content |
|---|---|
| `model/` | Hand-written model (`document`, `preproc`, `shared`, `creole`, `diagrams/`, `embedded/`) and `schema.json`. |
| `model/generated/` | Models generated from the upstream sources. Never edit by hand. |
| `extracted/` | Raw command regex trees dumped from the jar by the Java extractor. |
| `dist/` | The generated TextMate grammar (committed; reproducible from `model/`). |
| `tools/` | Python tooling: `extract`, `translate`, `model` (loader), `interp`, `emit`, `validate`, `report`; Java harness in `tools/extract` and `tools/oracle`. |
| `reports/` | Parity reports per corpus (`parity-*.json`, `.md`, slices in `parity/`) and classifications (`classify/`). |
| `docs/` | [Grammar guide](docs/grammar-guide.md), [command coverage](docs/coverage.md), [semantic gaps](docs/semantic-gaps.md). |
| `tests/` | pytest suite and the `vscode-textmate` proof (`tests/textmate`). |

## Prerequisites
- `uv` (Python 3.11+, dependencies in `pyproject.toml`), Node and npm, Java 21 (`javac`, `java`).
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
uv run python -m tools.emit.build        # model/ -> dist/plantuml.tmLanguage.json (no jar needed)
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

## Validate
These five gates must pass:

```sh
uv run pytest --cov=tools --cov-branch --cov-fail-under=90
uv run ruff check . && uv run ruff format --check .
npm test
uv run python -m tools.model.load --check model/
uv run python -m tools.extract.build
```

Without the jar and corpora, run `uv run pytest -m "not corpus"` for the tests that need no
external input.

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
[semantic gaps](docs/semantic-gaps.md)). Test suite: 3,993 tests pass (1 skipped, 148 expected failures that pin known gaps),
98.3% line and branch coverage of `tools/` (gate: 90%).

Details: [grammar guide](docs/grammar-guide.md) (model format, regeneration, troubleshooting),
[command coverage](docs/coverage.md), [semantic gaps](docs/semantic-gaps.md),
[CHANGELOG](CHANGELOG.md). Known limits of the TextMate grammar are listed in the guide,
section "Generated grammars".

## License
This project is licensed under the [MIT License](LICENSE).
