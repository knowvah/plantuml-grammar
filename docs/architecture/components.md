# Components

## plantuml-grammar

### Module structure
The `tools/` packages and the files they read and write. Each edge is labelled with what
crosses it.

```plantuml
@startuml
title plantuml-grammar: tools/ modules
skinparam componentStyle rectangle

component "config.py\n(env + upstream-pin.json)" as CFG
component "extract\n(build.py, run.py, Extract.java)" as EXTRACT
component "translate\n(iregex, ubrex, macros,\ndedupe, provenance)" as TRANSLATE
component "model\n(load, resolve, patch,\njava_regex)" as MODEL
component "interp\n(engine, dispatch, rules,\ncompile, scan, source)" as INTERP
component "emit\n(build, textmate,\ntextmate_regex, keywords)" as EMIT
component "validate\n(parity, parity_run,\nparity_core, oracle, corpus)" as VALIDATE
component "report\n(coverage, families,\nsemantic_gaps)" as REPORT
component "oracle\n(Oracle.java)" as ORACLE

folder "extracted/*.json" as EXTRACTED
folder "model/ (hand-written)\nmodel/generated/\nschema.json" as YAML
artifact "dist/plantuml.tmLanguage.json" as DIST
folder "reports/\n(parity, classify, oracle-cache)" as REPORTS
folder "docs/\n(coverage, semantic-gaps)" as DOCS

EXTRACT --> CFG : jar path, pin
EXTRACT --> EXTRACTED : writes I1 trees
TRANSLATE --> EXTRACTED : reads
TRANSLATE --> YAML : writes model/generated
MODEL --> YAML : loads + schema-validates
INTERP --> MODEL : ResolvedModels, Part
EMIT --> MODEL : ResolvedModels
EMIT --> DIST : writes
VALIDATE --> ORACLE : JVM subprocess
VALIDATE --> INTERP : accepts()
VALIDATE --> REPORTS : slices, merged reports
REPORT --> REPORTS : reads classifications
REPORT --> DOCS : writes
@enduml
```

### Interpreter types
The interpreter's main types. The model is the input data; `Interpreter` is the runtime
that applies it.

```plantuml
@startuml
title plantuml-grammar: interpreter (tools/interp)
hide empty members

class Interpreter {
  +accepts(text) : Verdict
  -_attempt(candidate)
  -_candidate(stack, line)
  -_apply(stack, rule)
}
class Dispatcher {
  +plan(keyword) : candidates
}
class RuleBook {
  +rules(context) : Rule[]
}
class Rule {
  regex
  kind : single|multiline|bracket|join
  push / pop / set
}
class Verdict {
  accepted : bool
  diagram
  status
  first_failure : FirstFailure
}
class ResolvedModels
class Deadline
class "source.Line" as Line

Interpreter --> Dispatcher : start keyword ->\nordered diagram models
Interpreter --> RuleBook : stack-top context rules
RuleBook --> Rule : builds lazily\n(compile.compile_part)
Rule ..> ResolvedModels : compiled from Part
Interpreter ..> Line : consumes stream
Interpreter ..> Deadline : bounds scan_*\n(multiline/bracket/join)
Interpreter --> Verdict : returns
Dispatcher --> ResolvedModels : top_models
@enduml
```

### Model layering
- `model/schema.json` (JSON Schema 2020-12) validates every YAML file.
- Hand-written files:
  - `model/document.yaml`, `preproc.yaml`, `shared.yaml` and `creole.yaml`.
  - `model/diagrams/*.yaml`, which refine generated entries with `overrides`,
    `insert_before` and `insert_after`.
  - `model/embedded/*.yaml`.
- Generated files: `model/generated/gen-*.yaml` and `gantt-lang.yaml`, each headed "GENERATED
  by tools/translate - do not edit".
- `load_dir` puts every file into one namespace, and a file's id must equal its stem.
  `resolve` then:
  1. merges model-level `include`;
  2. splices context `{include: NAME|MODEL#CONTEXT}`;
  3. substitutes `{ref: VAR}`;
  4. applies patches, failing on any that no longer match.

## plantuml-ts

```plantuml
@startuml
title plantuml-ts: render pipeline modules
skinparam componentStyle rectangle

component "index.ts\n(renderSync, render,\nrenderPages, renderAll)" as API
component "core/tim + preprocessor\n(!include, !define, stdlib)" as TIM
component "BlockUmlBuilder /\nblock-extractor" as BLOCKS
component "registered-plugins.ts\n+ diagrams/*" as PLUGINS
component "skin / style / theme\n+ measurer" as STYLE
component "graph-layout + svek\n(DOT build / read back)" as SVEK
component "core/elk\n(lazy elkjs)" as ELK
component "assemble-svg, klimt,\ncreole, svg*" as SVG
component "@knowvah/dot-engine" as DOT
folder "packages/*\n(stdlib, sprites, emoji)" as ASSETS
folder "oracle/\n(pin.json, goldens, jars)" as ORACLE

API --> TIM : source + includeStore
TIM --> ASSETS : stdlib registry
API --> BLOCKS : @start..@end blocks
API --> PLUGINS : pick plugin, parse to AST
PLUGINS --> STYLE : theme, skinparams, text widths
PLUGINS --> SVEK : graph diagrams: layoutSync
SVEK --> DOT : createGraph / render / getLayout
PLUGINS --> ELK : options.elk only
API --> SVG : assemblePages(geometry, AST)
ORACLE ..> API : parity goldens (tests only)
@enduml
```

## plantuml-plugins

```plantuml
@startuml
title plantuml-plugins: package graph
skinparam componentStyle rectangle

component "@knowvah/plantuml-core\n(renderAll, ./browser, ./element)" as CORE
component "@knowvah/plantuml-markdown-it" as MDIT
component "@knowvah/plantuml-react" as REACT
component "vitepress-plugin-plantuml" as VP
component "eleventy-plugin-plantuml" as ELEVENTY
component "docusaurus-plugin-plantuml" as DOCU
component "plantuml-vscode\n(extension + render-worker)" as VSC
component "plantuml-jetbrains\n(Kotlin + JCEF bundle)" as JB
component "@knowvah/plantuml-ts\n+ plantuml-stdlib\n(sibling checkout)" as ENGINE
artifact "syntaxes/plantuml.tmLanguage.json\n(hand-written, 14 rules)" as GRAMMAR

CORE --> ENGINE : link: dependency
MDIT --> CORE : workspace:*
REACT --> CORE : workspace:*
VP --> MDIT : fence rule
VP --> CORE : build-time renderAll
ELEVENTY --> MDIT : fence rule
DOCU --> REACT : MDX component
DOCU --> CORE : remark render
VSC --> MDIT : Markdown preview
VSC --> CORE : renderDiagram in worker
VSC --> GRAMMAR : contributes.grammars
JB --> CORE : esbuild bundle
@enduml
```
