## Observation: Java 21 regex semantics probed (java 21.0.1, tests/fixtures/java_regex/Vectors.java)
- **Context**: deciding what `tools/model/java_regex.py` must rewrite; Pattern2 compiles with CASE_INSENSITIVE only (Pattern2.java:114), no UNICODE_CASE / UNICODE_CHARACTER_CLASS anywhere in src/main/java at 97a5992.
- **Finding**: `.` refuses `\n \r U+0085 U+2028 U+2029` (VT, FF, NUL match). `\d \w \s \D \W \S`, POSIX `\p{Alpha}` ... are ASCII (`\s` = `[ \t\n\x0B\f\r]`: VT yes, NBSP/NEL/U+2003 no). `\p{L}` is Unicode. CI folds ASCII only: `k` vs U+212A, `s` vs U+017F, `i` vs U+0131, U+00E9 vs U+00C9, `[a-z]` vs U+212A all fail; `[Z-a]` ci matches `z` and `A`. `\p{Lu}`/`\p{Ll}`/`\p{Lt}` under CI = any cased letter (also non-ASCII); `\p{Upper}` under CI = `[A-Za-z]`; `\P{Lu}` under CI rejects `a`. Back references under CI fold ASCII only. `$` and `\Z` match before ONE final terminator (`\r\n`, `\n` not between `\r\n`, `\r`, U+0085, U+2028, U+2029); `\z` does not.
- **Impact**: all of this differs from Python `regex`. The pattern text a model carries is Java's; consume it only through `to_python`.
- **Confidence**: High (probe + Pattern javadoc, docs.oracle.com/en/java/javase/21/docs/api/java.base/java/util/regex/Pattern.html)

## Observation: Java `\b` is not the documented `(?<=\w)(?=\W)|...`
- **Context**: property tests against Java (1,083 random patterns x 227 strings).
- **Finding**: `Pattern.Bound` treats a non-spacing mark (Mn) as a word character when a letter or digit (Unicode `isLetterOrDigit`, BMP) precedes it, skipping other marks. `a\b` finds no boundary in `a` + U+0301, `\B` does. Supplementary base characters never count (Java walks UTF-16 units). `to_python` reproduces it with lookbehinds.
- **Impact**: do not simplify `\b` to an ASCII word boundary.
- **Confidence**: High (vectors.json agrees on every comparable pair)

## Observation: Python `regex` cannot do ASCII-only case folding with a flag
- **Context**: T08 said ASCII breaks `\p{L}`; I checked the other half.
- **Finding**: `(?ai:k)` still matches U+212A and `(?ai:ſ)` matches `s`; the ASCII flag does not restrict IGNORECASE folding in `regex` 2026.9.29, and `(?a:\p{L})` rejects é. So no flag helps; letters are expanded to `[kK]` classes and ranges gain their other-case twin, with no `(?i)` left in the output.
- **Impact**: any new consumer of ci regexes must go through `to_python` / `literal_to_python`.
- **Confidence**: High

## Observation: dropping `^...$` means the implicit `$` must be re-added
- **Context**: translator strips the outer anchors of every IRegex command (tools/translate/iregex.py); upstream matches with `find()` (RegexComposed.java:112-118).
- **Finding**: `^X$` accepts X followed by one final line terminator. Once `.` refuses U+2028/U+0085/U+2029, `title a<U+2028>` would become a false reject unless the whole pattern tolerates that terminator. `line_pattern(body)` = `(?:body)(?:\r\n|(?<!\r)\n|[\r\x85\u2028\u2029])?`; `compile_part` applies it. Residual: `Pattern.matches()` users (no implicit `$`) get the tolerance too.
- **Impact**: Other `regex` consumers matching a whole line need the same wrapper.
- **Confidence**: High (vectors, mode `line`)

## Observation: unit gluing is decided by the model's factory, not by a model key
- **Context**: joins in json.yaml / board-files-git-files.yaml could not stop at `</style>` when a `{{` line intervened.
- **Finding**: 28 extracted factories do not extend PSystemCommandFactory (24 `opaque-no-regex-field` plus Colors, Ditaa, Dot, Sudoku, which have a regex field but extend PSystemSingleLineFactory/PSystemBasicFactory); `tools/interp/factories.py` lists them and a corpus test checks the superclass chains at 97a5992. Scanners take `glue=False` for their rules. No model edit needed, and `Join` bundles start/max_lines/glue (5-parameter limit).
- **Impact**: a new non-command factory must be added to NON_COMMAND_FACTORIES (the extracted-opaque test fails if an opaque one is missing).
- **Confidence**: High

## Observation: full-suite wall time is dominated by 37 s session setups
- **Context**: running tests/families + tests/layers.
- **Finding**: every family test module loads and resolves all models (about 37 s under load, 12 s alone); 31 modules in parallel make a ~15 minute serial run look like a hang.
- **Impact**: run family modules individually when iterating.
- **Confidence**: High

## Observation: A/B parity (frozen model/, old vs new interpreter)
- **Context**: vega, plantuml-ts, pdiff, same frozen models plus the embedded-welcome key.
- **Finding**: zero FR before and after; the only verdict changes are the two pevoma-08-vido726 blocks (FA fixed by `empty_needs_end`). The corpora hold no block where Java's ASCII classes or ASCII case folding change a verdict; the semantic gap is closed by construction (vectors), not visible in the corpora.
- **Confidence**: High

