# System architecture

These are three repositories with no runtime services. Every connection is a filesystem
path, a subprocess or an npm package. The diagram shows the current state. The dashed edges
labelled "planned" are the intended wiring of the generated grammar and are not yet in
place.

```plantuml
@startuml
title knowvah PlantUML toolchain (current state, 2026-10-23)
skinparam componentStyle rectangle

package "plantuml-grammar (Python + Java)" as PG {
  component "Extract / Oracle\n(Java, tools/extract, tools/oracle)" as JAVA
  component "Translate + Model\n(tools/translate, tools/model)" as MODEL
  component "Interpreter\n(tools/interp)" as INTERP
  component "TextMate emitter\n(tools/emit)" as EMIT
  component "Parity + reports\n(tools/validate, tools/report)" as PARITY
  artifact "dist/plantuml.tmLanguage.json" as TM
}

package "plantuml-ts (TypeScript)" as PTS {
  component "@knowvah/plantuml-ts\nrenderer" as ENGINE
  artifact "oracle stock jar\n(1.2026.8beta1)" as JAR
  folder "tests/corpus\n(4,401 files)" as CORPUS
  component "docs-site\n(VitePress + Shiki)" as DOCS
}

package "plantuml-plugins (TypeScript, Kotlin)" as PP {
  component "@knowvah/plantuml-core\n+ host plugins" as CORE
  component "VS Code extension" as VSC
}

folder "External: PlantUML source checkout,\nvega + pdiff corpora" as EXT
component "@knowvah/dot-engine\n(npm)" as DOT

JAVA --> JAR : loads command classes\n(JVM subprocess)
JAVA --> MODEL : extracted/*.json
EXT --> MODEL : provenance\n(git show <sha>)
MODEL --> INTERP : ResolvedModels
MODEL --> EMIT : ResolvedModels
EMIT --> TM : writes
PARITY --> INTERP : accepts(text)\n(process pool)
PARITY --> JAVA : Oracle verdicts\n(JVM subprocess)
PARITY --> CORPUS : reads *.puml
PARITY --> EXT : reads *.puml
ENGINE --> DOT : graph layout\n(npm import)
CORE --> ENGINE : renderAll / renderSync\n(link: dependency)
VSC --> CORE : render in worker thread
DOCS ..> VSC : hand-copied\nhand grammar
TM ..> VSC : planned: replace\nhand grammar
TM ..> DOCS : planned: Shiki grammar
@enduml
```

## Communication summary
| From | To | Mode | Protocol / mechanism |
|---|---|---|---|
| tools/extract, tools/validate/oracle.py | PlantUML jar | sync, batch | `java -cp build/java:<jar>` subprocess; paths on stdin, one JSON verdict line per file on stdout |
| tools/translate/provenance.py | PlantUML source checkout | sync | `git show <pin-sha>:<file>` subprocess |
| tools/validate/parity_run.py | tools/interp | parallel, in process | `ProcessPoolExecutor`, `interp.accepts` |
| tools/emit | editors | build artifact | JSON file (not yet published to npm) |
| plantuml-plugins core | plantuml-ts | in process | ES module import through a `link:` dependency |
| VS Code extension host | render worker | async | `worker_threads` message (`{ok, svg}`) with a configurable timeout |
| plantuml-ts | dot-engine | in process | npm import (`createGraph` / `render` / `getLayout`) |
