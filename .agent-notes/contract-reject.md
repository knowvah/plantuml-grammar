## Observation: upstream backtracks at the start line for unterminated multiline commands
- **Context**: implementing `require_pop` (queued by the common family).
- **Finding**: `PSystemCommandFactory.getCandidate` (:236-240 at 97a5992) does `continue` when `isMultilineCommandOk` returns null, so the next command is tried for the same start line; the "queued" wording (start line fails) holds only when no later command matches. The interpreter now backtracks to the outermost open `require_pop` push and resumes with the following rules.
- **Impact**: a later catch-all (e.g. salt `CommandAnything`) accepts the unterminated start line, exactly like upstream; models needing a hard reject must also place a `reject` entry or no later match.
- **Confidence**: High

## Observation: pre-existing wrong citation `PSystemCommandFactory.java:193-201`
- **Context**: engine docstring cited it for the syntax error; at 97a5992 the syntax error is :169-175 (`executeFewLines`), execution error :180-187.
- **Finding**: corrected in tools/interp/engine.py.
- **Impact**: any new provenance `also` citation should use the numbers above.
- **Confidence**: High

## Observation: `\u` escapes now fail the loader
- **Context**: `\uXXXX` in a regex is rejected by PCRE2. Fixtures tests/interp/fixtures/classtoy.yaml and tests/emit/fixtures/contract/contract_class.yaml used `"\\ue100"`; changed to YAML `""` (literal char).
- **Finding**: generated models already use the literal form; `load --check model/` stays green.
- **Impact**: hand-written models must write non-ASCII as literal characters.
- **Confidence**: High
