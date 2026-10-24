# Data flows

## 1. Upstream bump: regenerate the model
A maintainer moves the pin to a new PlantUML commit. Every downstream artifact is
regenerated, and stale hand-written patches fail loudly.

```plantuml
@startuml
title Upstream bump (plantuml-grammar)
actor Maintainer as M
participant "tools.extract.build" as BUILD
participant "tools.extract.run" as RUN
participant "Extract.java\n(JVM)" as EXT
database "PlantUML jar" as JAR
participant "tools.translate.run" as TR
participant "provenance\n(git show)" as PROV
participant "tools.model.load\n--check" as LOAD
participant "report / emit /\nparity" as DOWN

M -> M : edit upstream-pin.json,\nset PLANTUML_JAR
M -> BUILD : run
BUILD -> BUILD : javac Extract + Oracle\ninto build/java
M -> RUN : run
RUN -> EXT : java -Dpin.sha -Dpin.version Extract
EXT -> JAR : walk each factory's commands\n(IRegex, UBrex walkers)
EXT --> RUN : extracted/*.json (I1)
M -> TR : run
TR -> TR : iregex / ubrex / ubrex_gantt\ntranslate, dedupe
TR -> PROV : FQCN -> file:line at pin sha
PROV --> TR : citations
TR --> M : model/generated/*.yaml (I2)
M -> LOAD : run
LOAD -> LOAD : schema + regex + id checks,\nresolve, apply_patches
alt a patch no longer matches
  LOAD --> M : ModelError (stale override/insert)
else clean
  LOAD --> M : ok
  M -> DOWN : coverage (missing commands),\nemit, parity
end
@enduml
```

## 2. Parity validation against the jar
This flow is how correctness is measured. Each `@start...@end` block is judged by both the
jar and the interpreter, and every disagreement is classified.

```plantuml
@startuml
title Parity run: tools.validate.parity --corpus all
participant "parity.run" as P
participant "corpus.enumerate_corpora" as C
participant "oracle.oracle_verdicts" as O
database "reports/oracle-cache" as CACHE
participant "Oracle.java (JVM)\nSourceStringReader.getBlocks" as JVM
participant "parity_run\n(ProcessPoolExecutor)" as RUNNER
participant "interp.accepts" as I
participant "parity_core\n+ parity_io" as CORE
database "reports/" as R

P -> C : vega, plantuml-ts, pdiff roots
C --> P : *.puml paths
P -> O : paths
O -> CACHE : lookup (content + pin + ORACLE_VERSION)
CACHE --> O : hits
O -> JVM : misses as paths on stdin
JVM --> O : one JSON verdict per file\n(accepted, diagram_type, error_line)
O -> CACHE : store
O --> P : verdicts
P -> RUNNER : Jobs (one per block)
RUNNER -> I : block text (preprocessed and raw)
I --> RUNNER : Verdict
RUNNER --> P : BlockResults
P -> CORE : kinds_of(oracle, interp)
note right of CORE
  FR = jar accepts, model rejects
  FA = jar rejects, model accepts
  plus timeout, diagram_mismatch, raw_fr
end note
CORE -> R : classify via reports/classify/<family>.yaml,\nwrite parity/<corpus>/<family>.json
P -> CORE : merge, target_failures
CORE -> R : parity-<corpus>.json / .md
CORE --> P : exit 0 ok / 1 target missed / 2 env error
@enduml
```

## 3. Highlighting and rendering a PlantUML file in VS Code
This is the user-facing editor flow. Highlighting comes from the hand-written grammar
today. The planned swap replaces only the grammar file, with plantuml-grammar's generated
`dist/plantuml.tmLanguage.json`, which has the same scope `source.plantuml`.

```plantuml
@startuml
title Edit + preview a .puml file (plantuml-plugins VS Code extension)
actor User
participant "VS Code" as VS
participant "TextMate grammar\nsource.plantuml" as TM
participant "extension.ts\nPreviewManager" as EXT
participant "PlantUmlRenderService" as SVC
participant "render-worker.ts\n(worker_threads)" as W
participant "@knowvah/plantuml-core\n/browser" as CORE
participant "@knowvah/plantuml-ts\nrenderSync" as ENG
participant "Webview" as WV

User -> VS : open diagram.puml
VS -> TM : tokenize (language plantuml)
TM --> VS : scopes -> colors
User -> VS : plantuml.showPreview
VS -> EXT : previews.show(document)
EXT -> SVC : render({source, theme})
SVC -> W : spawn worker + start timeout\n(renderTimeoutSeconds, default 60)
W -> CORE : renderDiagram(source)
CORE -> ENG : renderSync(source, options)
ENG --> CORE : SVG (or error SVG, never throws)
CORE --> W : {ok, svg}
W --> SVC : postMessage
alt timeout or worker error
  SVC -> W : terminate
  SVC --> EXT : {ok:false, message}
else success
  SVC --> EXT : {ok:true, svg}
end
EXT -> WV : previewDocument(svg) with CSP
User -> VS : edit text
VS -> EXT : onDidChangeTextDocument -> refresh
@enduml
```
