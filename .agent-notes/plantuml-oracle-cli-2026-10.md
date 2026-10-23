## Observation: --check-syntax gives no per-file verdict in batch mode
- **Context**: Planning the parity oracle for the command-model mission (stock jar 97a5992).
- **Finding**: `java -jar <jar> --check-syntax a.puml b.puml c.puml` prints one aggregate
  line ("Some diagram description contains errors") and exits 200; it does not say which
  file failed. Per-source verdicts are available in-process from
  `net.sourceforge.plantuml.syntax.SyntaxChecker.checkSyntax(String)` -> `SyntaxResult`
  (`getDiagramType()`, `isError()`, `getLineLocation()`, `getErrors()`).
- **Impact**: The oracle must be a small Java harness calling SyntaxChecker in one JVM,
  not the CLI. One JVM per file (~10.4k corpus files) would take hours.
- **Confidence**: High

## Observation: !define outside @startuml is not applied by --preproc
- **Context**: Probing `--preproc` with `!define X class` placed before `@startuml`.
- **Finding**: Output kept `X Foo` unexpanded; the preprocessed source is written to
  `<name>.preproc` next to the input (not stdout).
- **Impact**: Preprocessor scope is per block; fixtures that test L1 must put
  directives inside the @start/@end block.
- **Confidence**: High
