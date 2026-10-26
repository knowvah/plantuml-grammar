# Grammar guide

The canonical artifact of this repository is the YAML command model under `model/`.
The interpreter runs it and the TextMate grammar is generated from it. This guide defines
the model format (contract I2), naming conventions and the layers. Machine-readable
shape: `model/schema.json` (JSON Schema 2020-12, `additionalProperties: false`
everywhere). Vocabulary is borrowed from
[sublime-syntax](https://www.sublimetext.com/docs/syntax.html).

## Model format

One model per file: `model/**/*.yaml`. The loader walks the tree recursively and ignores
`schema.json`.

```yaml
schema_version: 1
id: class
layer: diagram
diagram: CLASS
include: [shared, creole]
variables:
  COLOR: {regex: "#\\w+"}
contexts:
  main:
    - command: CommandCreateClass
      provenance: {class: net.sourceforge.plantuml.classdiagram.command.CommandCreateClass,
                   file: src/main/java/.../CommandCreateClass.java, line: 123, engine: IRegex}
      kind: single
      parts:
        seq:
          - {literal: class, ci: true}
          - {regex: "\\s+"}
          - {ref: COLOR}
      push: class_body
    - include: common_commands
```

### Keys

| Key | Where | Meaning | sublime-syntax |
|---|---|---|---|
| `schema_version` | top | Always `1`. | none (added) |
| `id` | top | Unique model id; must equal the file stem. | none (a syntax is identified by its file) |
| `layer` | top | `document`, `preproc`, `diagram` or `shared` (see Layers). | none (added) |
| `diagram` | top | Upstream `DiagramType` name. Required when `layer: diagram`, forbidden otherwise. | none (added) |
| `empty_needs_end` | top (`diagram`) | Boolean, default false. With an `empty` context: a block that has a start line but no end line (a preprocessor-truncated block) is refused instead of run through `empty` (see "Diagram dispatch"). | none (added) |
| `include` | top | List of model ids whose variables and contexts become visible. | `extends` (inherit contexts) |
| `variables` | top | Map `UPPER_SNAKE` name to a Part. | `variables` (there: name to regex string) |
| `contexts` | top | Map `snake_case` name to an ordered list of entries. Order is the upstream `initCommandsList` order and is significant. | `contexts` |
| `overrides` | top (`diagram`, `shared`) | Map key to a partial entry, shallow-merged over each matching entry of the resolved model (see "Refining generated models"). | none (added) |
| `insert_before` / `insert_after` | top (`diagram`, `shared`) | Map key to a list of full entries inserted immediately before / after each matching entry. | none (added) |
| `include: NAME` | entry | Splice another context in place (rules below). | `include` |
| `command` | entry | Upstream `Command` simple class name; also the rule id. | none (added; a rule has no id) |
| `provenance` | entry | Where the rule comes from: `class` (FQCN, required), `file`, `line` (pinned upstream sha), `engine` (`IRegex` or `UBrex`), `also` (see below). | none (added) |
| `kind` | entry | `single`, `multiline`, `multiline-bracket` or `opaque` (see "Multiline kinds"). | none (added) |
| `parts` | entry | The Part matched by the command's first line. | `match` |
| `end` | entry | Part closing a `multiline` command. Forbidden for every other kind. | `escape` / pop-rule `match` (closest) |
| `join: {max_lines: N}` | entry | `multiline` only, instead of `end`: the lines are joined and re-matched against `parts` (see below). | none (added) |
| `push` | entry | Context to enter after matching. | `push` |
| `pop: true` | entry | Leave the current context. | `pop` |
| `set` | entry | Replace the current context by the named one. | `set` |
| `provenance.also: [str]` | entry | Optional extra `path:line` (or `path:first-last`) citations at the pin, each matching `^src/main/java/.+\.java:\d+(-\d+)?$`. The loader checks the pattern only; a corpus test checks that every citation in `model/` resolves at 97a5992. | none (added) |
| `require_pop: true` | entry | Only with `push` (also allowed in `overrides`): ending the block while the pushed frame is still open skips the command, so the interpreter backtracks to the pushing line (see "Unterminated bodies and rejected lines"). | none (added) |
| `reject: true` | entry | `single` only, no `push`/`pop`/`set` (also allowed in `insert_before`/`insert_after` entries and `overrides`): when the entry is selected the attempt fails at that line (mirrors `CommandExecutionResult.error`). Emitters drop the entry. | none (added) |
| `emit: false` | entry | Interpreter-only entry (also allowed in `overrides` and inserts): the TextMate emitter drops it exactly like a `reject` entry (`tools/emit/skip.py`); the interpreter uses it normally. For state heads whose generated twin already accepts the same lines. | none (added) |
| `gives: FLAG` / `needs: FLAG` | entry | Snake_case diagram flag (also allowed in `overrides`, `insert_before`/`insert_after` entries): the entry sets / requires the flag, checked once at the end of the body (see "Diagram flags and untrimmed matching"). Emitters ignore both. | none (added) |
| `trim: false` | entry | `single` only (also allowed in `overrides` and inserts): the entry matches the line as the command loop receives it, with leading and trailing blanks. Emitters ignore it. | none (added) |
| `refined_by` | entry | Id of the model whose `overrides` changed this entry; set by the resolver, never hand-written. | none (added) |

### Multiline kinds

Mirrors `command/PSystemCommandFactory.java:268-307` (`isMultilineCommandOk`) at 97a5992.
Every consumer (interpreter, emitters) must implement these exactly as written here.

| Kind | First line | Completion |
|---|---|---|
| `single` | `parts` matches the whole trimmed line (the untrimmed line with `trim: false`). | That line. |
| `multiline` + `end` | `parts` matches. | First later line whose trimmed text fully matches `end` (`CommandMultilines2.java:79-110`). |
| `multiline` + `join` | (lines joined) | Lines `1..k` (k ≤ `max_lines`+1) joined with U+E100 (`utils/BlocLines.java:296`, `jaws/Jaws.java:47`) fully match `parts`; the smallest such k wins (`CommandDecoratorMultine.java:77-93`, cap at `PSystemCommandFactory.java:281`). k = 1 is the single-line case. |
| `multiline-bracket` | `parts` matches (it ends in `{`). | Bracket depth returns to 0: depth starts at 1, a trimmed line ending in `{` adds one, ending in `}` removes one (`CommandMultilinesBracket.java:64-96`). |
| `opaque` | `parts` matches. | Rest of the block (non-command factory). |

Unit gluing (`{{ ... }}` lines are one unit, `PSystemCommandFactory.java:288-307`) belongs
to command factories only. The factories that are not `PSystemCommandFactory` subclasses
(`PSystemAbstractFactory` readers such as JSON, YAML, HCL, files and git, the single-line,
basic and welcome factories) read plain lines (`jsondiagram/StyleExtractor.java:63-103`),
so their `multiline`, `multiline-bracket` and `join` scans treat a `{{` line as an ordinary
line. The interpreter decides by the model's `factory`
(`tools/interp/factories.py:NON_COMMAND_FACTORIES`, checked against the upstream superclass
chains); no model key is involved.

The TextMate emitter cannot express a completion rule exactly; it approximates it and
documents the approximation in its module docstring: `join` as a single line, bracket depth
as a body closed by a line `\s*\}`.

### Unterminated bodies and rejected lines (`require_pop`, `reject`)

**`require_pop: true`.** Mirrors `PSystemCommandFactory.getCandidate`
(`command/PSystemCommandFactory.java:223-247`, `isMultilineCommandOk` at `:268-286`): a
multiline command whose end never arrives returns `null` and the factory does `continue`,
trying the *next* command for the same start line; only when none matches does the start line
fail (`:169-175`). A model that enters a body as a context (`push`) cannot say that the body
must close, so `require_pop` marks the pushing entry. Interpreter semantics:

* When the block ends while a `require_pop` frame is still on the stack, the interpreter
  backtracks to the **outermost** still-open `require_pop` push (upstream's outer scan
  swallows the inner lines, so an inner command never starts), restores the stack as it was
  before that push, and resumes **at the pushing line with the rules after the pushing
  rule** in the same context.
* If no later rule matches the pushing line, the attempt fails at the pushing line.
* Frames closed by `pop` before the block ends are final, and a body line no rule accepts
  still fails at that line (no backtracking): only the end of the block triggers it.
* The TextMate emitter ignores the key: an unclosed region extends to the end of the block.

**`reject: true`.** Mirrors `CommandExecutionResult.error` -> `EXECUTION_ERROR`
(`PSystemCommandFactory.java:180-187`): the command's regex matched, so the factory fails
and no later command is tried. An entry with `reject` makes the attempt fail at its line
when it is the first match in context order, so it must precede the entries it shadows
(typically via `insert_before` the unnarrowed generated rule). The TextMate emitter drops
`reject` entries and also skips `join` entries whose `parts` need U+E100 on every path
(they can never match one line, see `tools/emit/skip.py`).

### Diagram flags and untrimmed matching (`gives`, `needs`, `trim: false`)

**Flags.** Some upstream errors are final-state failures that no context stack can express,
because they depend on the whole body regardless of order: a gantt with separators or
groups but no real task throws a `NullPointerException` in `TimeBoundsData.durationInDays`,
which `PSystemBuilder` catches as `Throwable` and reports as an execution error
(`PSystemBuilder.java:275-280`). `gives: <flag>` and `needs: <flag>` model it. Flags are
monotone and order-free:

* The interpreter collects the entries it selects in the diagram's own command loop.
  When the body ends (and no `require_pop` frame is pending), the attempt fails **at the
  block's `@end` line** (its last line when there is none) if a selected entry `needs` a
  flag that no selected entry `gives`. A line no command accepts still fails at that
  line first.
* Where the give happens does not matter: before or after the need, in a pushed
  context, after the pop. Pushing a context does not hide or restore flags.
* Backtracking (`require_pop`) discards the entries selected after the abandoned push,
  flags included; the entry that is re-matched at the pushing line counts afresh.
* In raw mode the preproc model's entries never contribute: it runs as a separate filter.
* `reject` entries fail the attempt at their line before any final-state check.
* The TextMate emitter ignores both keys, so it is wider than the interpreter for such
  bodies; its docstring says "`gives`/`needs` (diagram flags, final-state checks) are
  ignored."

```yaml
- {command: Separator, ..., needs: real_task}   # `-- x --`
- {command: Task, ..., gives: real_task}        # any real task
```

**Untrimmed matching.** `SingleLineCommand2(doTrim=false, ...)` matches the first line
as is (`command/SingleLineCommand2.java:76-81` `myTrim2`, called at `:93`, matched at
`:102`); the default trims with `StringUtils.trin` (`StringLocated.getTrimmed`).
`trim: false` selects the first behaviour (`single` only). The text is `Line.text`, the line
as `preproc/ReadLineReader.java:89-102` returns it: `readLine` ends a line at `\n`, `\r` or
`\r\n`, a leading U+FEFF is dropped, and U+2013 becomes `-`; tabs and trailing blanks are
kept (nothing else rewrites the text before the command loop; inner `/' ... '/` comment
removal, `StringLocated.removeInnerComment`, is not reproduced). The translator emits
`trim: false` for every extracted command whose `doTrim` field is false (`SingleLineCommand2`
and `UBrexSingleLineCommand2` both carry the field; at 97a5992 only IRegex commands use
`false`: 23 classes, 25 command instances). A regex that never expected leading blanks now
fails on an indented line, exactly like upstream, so hand-written overrides of those entries
that rely on trimming must allow `\s*` explicitly.

### Case sensitivity

Upstream compiles every IRegex command through `Pattern2` with `CASE_INSENSITIVE`
(`regex/Pattern2.java:114`), so generated regex Parts of such commands carry `ci: true`.
Plain `java.util.regex.Pattern` patterns (some non-command factories) are
case-sensitive and carry no `ci`. Hand-written models state `ci` explicitly where needed.
`ci` folds ASCII letters only (see "Regex semantics (java.util.regex)").

`push`, `pop` and `set` are mutually exclusive. `push`/`set` targets must name a context
visible from the model.

### Parts

A Part is exactly one of:

| Form | Meaning | sublime-syntax |
|---|---|---|
| `{seq: [Part]}` | Sequence. | concatenation inside a regex |
| `{alt: [Part]}` | Ordered alternatives. | `a\|b` |
| `{opt: Part}` / `{star: Part}` / `{plus: Part}` | `?`, `*`, `+`. | `?`, `*`, `+` |
| `{ref: VAR}` | Use a variable. Inlined by the resolver. | `{{VAR}}` interpolation |
| `{regex: str, ci?: bool, name?: str, scope?: str}` | A regex; `ci: true` = case-insensitive (absent = case-sensitive), `name` labels the capture, `scope` is a TextMate scope. | `match` + `scope` / `captures` |
| `{literal: str, ci: bool, scope?: str}` | Fixed text; `ci` = case-insensitive. | literal `match` with `(?i)` |

Regex rules (checked by the loader):

* Regexes are **expanded**: the upstream `%`-macros `%pLN`, `%s`, `%q`, `%g`
  (`regex/Pattern2.java:54-59` at 97a5992) must not appear.
* A regex means what `java.util.regex` makes of it (see "Regex semantics" below).
  Each regex also compiles with the Python `regex` module (a superset of `re` in its default
  mode) once translated. `re` itself is not used because expanded `%pLN` contains `\p{L}\p{N}`.
  Oniguruma and PCRE compilation is checked by the emitter tasks.
* A `\uXXXX` escape inside a regex is a load error: PCRE2 rejects `\u`. Write the
  character itself (a YAML double-quoted `"\uE100"` is parsed to the literal character
  before the loader sees it, so it is fine; a regex that still contains a backslash followed
  by `u` after YAML parsing is not). `\\u` (escaped backslash, then `u`) is allowed.

### Include and ref semantics

* Model-level `include: [ids]` makes the included models' variables and contexts
  visible. Lookup order: the model itself, then its includes depth-first in listed order;
  the first definition wins, so a model overrides what it includes. The resolved model
  carries the merged contexts and variables, so `push`/`set` can name an included context.
* Entry `include: NAME` splices that context's entries at that position. NAME is tried
  as (1) a context visible from the model, (2) a model id, meaning that model's `main`
  context, and `MODEL#CONTEXT` addresses a specific context of a specific model. This
  mirrors sublime-syntax, where `include: ctx` is a context of the same file and
  `include: other.sublime-syntax` is the other file's `main`.
* `ref: VAR` is looked up lexically from the model that contains it (so a spliced
  entry keeps resolving against its defining model). A variable's value is itself a Part
  and may contain `ref`.
* Cycles are errors naming the path: `include cycle: A → B → A` (model ids, or
  `model.context` nodes for context splices) and `variable cycle: m.X → m.Y → m.X`.

### Diagram dispatch (`factory`, `start_map`)

Mirrors `PSystemBuilder.java:133-200` (factory order) and `:257-287` (try loop) at 97a5992.

* `factory: <SimpleName>` (diagram layer only) names the upstream `PSystemFactory` a
  diagram model implements. Generated models set it (`gen-class-diagram` →
  `ClassDiagramFactory`).
* `start_map: {<keyword>: [<factory>, …]}` (document layer only) maps a start keyword
  (`uml` for `@startuml`) to the factories tried for it, in `PSystemBuilder` order.
* For each factory the interpreter uses the **top** diagram model declaring it: the one
  no other model with the same `factory` includes (transitively). A hand-written family
  model therefore sets the same `factory` and `include`s the generated model it
  extends; it replaces the generated one in dispatch without editing `start_map`.
  Two top models for one factory is a load error.
* Keyword lookup mirrors `DiagramType.findStartTypes`: exact key, then a key that is a
  prefix of the keyword (`@startumlfoo` → `uml`). The word `start` is case-sensitive
  (`@STARTUML` opens no block, `StartUtils.isStartDirective`); the keyword folds ASCII
  `A`-`Z` only (`@startUML` is `uml`, `@startſalt` is not `salt`). A keyword no key covers is
  `PSystemUnsupported` (`PSystemErrorUtils.java:58-59`, `PSystemBuilder.java:283-284`),
  which is not a `PSystemError`: the verdict is accepted with `diagram`/`model` `None`,
  as the oracle reports it.
* An explicit `start_map` argument to `accepts` overrides the document model; entries
  may name factories or model ids.
* Empty bodies: command factories reject a body with no non-blank line at the start
  line. A diagram model that accepts an empty body declares an `empty` context; the
  body's lines followed by the `@end` line run through it (`embedded-welcome`,
  `embedded-json`, …). `empty_needs_end: true` on that model refuses a block that has a
  start line but no end line: its source is one line long, and `PSystemWelcomeFactory`
  needs exactly two (`eggs/PSystemWelcomeFactory.java:52`), while
  `PSystemBasicFactory`-style factories accept the truncated block
  (`command/PSystemBasicFactory.java:101`), so the refusal is opt-in per model
  (`embedded-welcome` sets it).
* `Verdict.diagram` is the accepting model's `diagram` (compare with the oracle's
  `diagram_type`, which is `null` for non-`TitledDiagram` results); `Verdict.model` is
  its id.

### Refining generated models (`overrides`, `insert_before`, `insert_after`)

A hand-written diagram model replaces its generated base in dispatch (see above) and
inherits the base's contexts, but must not edit `model/generated/**`. These three
model-level keys refine individual generated entries in place, keeping upstream order.
They are allowed on `layer: diagram` and `layer: shared` models only.

```yaml
overrides:        # key -> partial entry, shallow-merged over each matched entry
  CommandCreateClassMultilines: {push: class_body}
  CommandFootboxIgnored: {remove: true}   # drops the matched entry
insert_before:    # key -> [full entries] placed immediately before each matched entry
  CommandCreateClass: [{command: ..., provenance: ..., kind: single, parts: ...}]
insert_after:     # same, immediately after
  CommandNamespace: [...]
```

**Keys.** A key matches an entry when it equals the entry's `command` (rule id, e.g.
`CommandFactoryNote_1`) or the simple class name of `provenance.class` (the part after
the last `.`, with `$` replaced by `_`). A class-name key matches every repeat of that
class. Keys live in one id space for the whole resolved model: they apply in every
context, after entry-level `include` splices are expanded. Beware that a hand-written
entry whose `provenance.class` is the same class is matched by a class-name key too; use
the unique `command` id as key, or a different provenance class, to avoid that.

**Collection.** Patches are collected from the model and its transitive model-level
includes in resolver scope order, key by key: the model's own declaration of a key wins
over an included one and is used as is (partial entries are not merged across models).
Different keys that hit one entry (a `command` id and a class name) are all merged into it,
the included model's first, so where they set the same field the model's own wins. A
`layer: shared` model such as `common` can therefore carry refinements for common
commands that apply to every diagram model including it. A shared model's patches never
apply to the shared model itself. `refs` inside patch entries resolve in the scope of the
model that declared them; `push`/`set` targets must be visible from the model being
resolved.

**Order of application.** Removes, then overrides, then `insert_before`/`insert_after`.
Inserted entries are not matched by overrides. Several inserts on one entry keep
declaration order. An insert key matching a removed entry is an error.

**Merge semantics.**

* The override's keys replace the entry's keys wholesale (`parts` is replaced, not merged).
  `command` and `provenance` are kept unless the override sets them.
* `null` deletes a key: `pop: null`, `push: null`, `set: null`, `end: null`, `join: null`.
  Needed to switch transition kind or turn a `multiline` into a `single`
  (`{kind: single, end: null}`).
* `remove: true` must be the only key of its patch.
* The merged entry gets `refined_by: <model id>` (the declaring model; the last one when
  several keys match) so provenance stays honest.
* The merged entry is validated against the entry schema: `push`/`pop`/`set` stay
  mutually exclusive, `multiline` still needs exactly one of `end`/`join`, `end`/`join`
  stay forbidden for the other kinds. Replacing `pop: true` by a `push` therefore needs
  `pop: null` in the same override.

**Errors** (all carry the declaring file and a JSON pointer such as
`/overrides/CommandCreateClassMultilines`):

* a key matching no entry in a diagram model that collects it, unless the winning
  declaration comes from an included `layer: shared` model (common commands are absent
  from some factories);
* a merged entry that violates the entry schema, or an unknown `push`/`set` context;
* an insert relative to a removed entry.

The loader also regex-checks `parts`/`end` inside patches. `Model` carries `overrides`,
`insert_before` and `insert_after` verbatim; `ResolvedModel` contexts already contain
the result.

Worked example, `model/diagrams/class.yaml`. It extends the generated class diagram and
the shared `common` model, refines two generated entries and adds one hand-written rule
before `CommandCreateClass`:

```yaml
schema_version: 1
id: class
layer: diagram
diagram: CLASS
factory: ClassDiagramFactory
include: [gen-class-diagram, common]    # generated `main` is inherited via the include

variables:
  COMMENT_LINE: {regex: "'.*", ci: false}

overrides:
  # 1. Enter the class body context instead of scanning for a closing line.
  CommandCreateClassMultilines:
    kind: single
    end: null                           # a single forbids `end`
    push: class_body
  # 2. This factory never reaches the footbox command.
  CommandFootboxIgnored: {remove: true}

insert_before:
  CommandCreateClass:                   # lands directly before the generated rule
    - command: CommandClassBlockComment
      provenance:
        class: net.sourceforge.plantuml.cucadiagram.BodierLikeClassOrObject
        file: src/main/java/net/sourceforge/plantuml/cucadiagram/BodierLikeClassOrObject.java
      kind: single
      parts: {ref: COMMENT_LINE}        # resolved in this model's scope

contexts:
  class_body:                           # visible to the `push` above
    - command: CommandClassBodyClose
      provenance: {class: net.sourceforge.plantuml.cucadiagram.BodierLikeClassOrObject}
      kind: single
      parts: {regex: "^\\s*\\}\\s*$"}
      pop: true
```

In the resolved `class` model `main` keeps the upstream order of `gen-class-diagram`
without `CommandFootboxIgnored`, `CommandClassBlockComment` sits right before
`CommandCreateClass`, and `CommandCreateClassMultilines` reads `kind: single`,
`push: class_body`, `refined_by: class`.

### Ids and files

`id` equals the file stem and must be unique across the whole tree: files under
`model/generated/` are identified by stem only (no directory prefix), so generated and
hand-written models share one global id namespace. Duplicates are reported with both
paths.

### Loading API

```python
from tools.model.load import load_dir  # load_dir(path) -> dict[str, Model]
from tools.model.resolve import resolve  # resolve(models) -> ResolvedModels
```

`python -m tools.model.load --check model/` exits non-zero on any error (schema
violation with file and JSON pointer, unexpanded macro, uncompilable regex, id/stem
mismatch, duplicate id, unknown include/ref/push target, cycle).

* `Model` (frozen dataclass): `id`, `layer`, `path`, `diagram`, `include`, `variables`,
  `contexts`, `factory` (str or None), `start_map` (dict keyword → list of factory
  names; empty unless `layer: document`). Parts and entries are plain dicts exactly as
  in the YAML.
* `ResolvedModels = dict[str, ResolvedModel]`; `ResolvedModel` has `id`, `layer`, `path`,
  `diagram`, `variables`, `contexts`, `factory`, `start_map`, `includes` (tuple of the
  transitive model-level include ids, depth-first, deduplicated), with no
  `include`/`ref` inside contexts or variables. `top_models(resolved) -> dict[factory,
  id]` (`tools.model.resolve`) gives the top model per factory; `resolve()` calls it, so
  two top models for one factory raise `ModelError` and fail `load --check`. Walk Parts
  recursively over the keys `seq`/`alt` (lists), `opt`/`star`/`plus` (single Part),
  and the leaves `regex`/`literal`. Resolved structures may share sub-objects: treat as
  read-only.
* `ModelError` carries `file`, `pointer`, `message`; `load_dir` raises `ModelLoadError`
  with `.errors` listing all of them.

## Regex semantics (java.util.regex)

A model regex has **Java semantics**, not Python's. Upstream compiles every `Pattern2` with
`Pattern.CASE_INSENSITIVE` only (`regex/Pattern2.java:114` at 97a5992), and no source under
`src/main/java` sets `UNICODE_CASE` or `UNICODE_CHARACTER_CLASS` (`git grep` at 97a5992 finds
neither). On Java 21 that gives (each line probed with `java` 21.0.1 and checked against the
[`java.util.regex.Pattern` documentation](https://docs.oracle.com/en/java/javase/21/docs/api/java.base/java/util/regex/Pattern.html):
"POSIX character classes (US-ASCII only)", `\d`/`\w`/`\s` "if UNICODE_CHARACTER_CLASS is not set",
`CASE_INSENSITIVE` "assumes that only characters in the US-ASCII charset are being matched" unless
`UNICODE_CASE` is set, `.` "any character except a line terminator unless the DOTALL flag is
specified"):

| Construct | Java 21 meaning | Python `regex` default |
|---|---|---|
| `.` | any code point except `\n \r U+0085 U+2028 U+2029` | anything except `\n` |
| `\d` `\w` `\s` and negations | ASCII: `[0-9]`, `[a-zA-Z_0-9]`, `[ \t\n\x0B\f\r]` | Unicode |
| `\b` `\B` | ASCII word boundary, except that a non-spacing mark after a letter or digit continues the word | Unicode |
| `\p{Alpha}`, `\p{Digit}`, `\p{Punct}`, `\p{Space}` ... (POSIX) | ASCII | Unicode properties |
| `\p{L}`, `\p{N}`, `\p{Nd}` ... | Unicode | Unicode |
| `ci` | folds ASCII letters only: `k` does not match U+212A, `é` does not match `É`; `\p{Lu}` `\p{Ll}` `\p{Lt}` become "any cased letter" | Unicode simple case folding |
| `$`, `\Z` | also match before one final line terminator | before a final `\n` |

Model regexes are therefore not valid Python `regex` input as written. **Consumers must
translate them with `tools.model.java_regex`** before handing them to the `regex` module:

```python
from tools.model.java_regex import line_pattern, literal_to_python, to_python

to_python(r"title\s+(.+)", ci=True)  # -> Python `regex` source, Java meaning
literal_to_python("class", ci=True)  # -> "[cC][lL][aA][sS][sS]"
line_pattern(body)  # body + one optional final line terminator
```

`to_python` is pure and rewrites `.`, the `\d \w \s \b \p{POSIX}` families (inside and
outside classes), ASCII case folding (letters become `[aA]` classes, ranges gain their other-case
twin, so no `(?i)` flag is used) and `$`/`\Z`. Constructs that are not Java but that models use
(`(?(DEFINE)`, `(?&name)`, `(?P<n>`, `(?P=n)`, conditionals, possessive quantifiers) pass through
unchanged; unsupported Java (`[a[b]]`, `&&`, `\h \v \R`, inline flags other than `i`) raises
`JavaRegexError`. `line_pattern` supplies the `$` of upstream's `^...$` wrapper, which the
translator strips from commands: use it for whole-line matching (`fullmatch`).

Known residual differences: a back reference under `ci` folds Unicode (Python) where Java folds
ASCII; lookbehind next to a supplementary character steps in UTF-16 units in Java; a
`Pattern.matches()` use (as opposed to `^...$` with `find()`) does not accept the trailing
terminator that `line_pattern` allows. Fidelity is tested against real Java:
`tests/fixtures/java_regex/vectors.json` holds Java's verdicts for 1,000+ generated patterns on
200+ strings, and a corpus-marked test regenerates them with `java` (`Vectors.java`) and compares.

Consumers: the interpreter (`tools/interp/compile.py`) translates every Part. The TextMate
emitter keeps the model's Java text: Oniguruma is its own engine (the emitter applies its own
ASCII conventions and documents the approximations).

## Naming conventions

* **Rule ids** are the upstream `Command` simple class names (`CommandCreateClass`) in
  the `command` key.
* **Variables** are `UPPER_SNAKE` (`COLOR`, `ARROW_BODY`).
* **Contexts** are `snake_case` (`main`, `class_body`). `main` is the entry context.
* **Model ids** are file stems: letters, digits, `_`, `-`.
* **Scopes** follow the
  [TextMate naming conventions](https://macromates.com/manual/en/language_grammars#naming_conventions)
  (`keyword.control`, `entity.name.type`, `string.quoted`, `comment.line`, ...) with the
  `.plantuml` suffix applied by the emitters, not in the model.

## Layers

Decision D3 splits PlantUML syntax into layers, each a set of models:

| Layer | Content |
|---|---|
| `document` | `@start*`/`@end*` framing and block detection. |
| `preproc` | Preprocessor directives (`!include`, `!define`, `!if`, ...). |
| `diagram` | One model per diagram type; `diagram` names the upstream `DiagramType`. |
| `shared` | Pieces reused by several models (colors, creole, arrows). |

**Raw mode (L1 hook).** `accepts(models, block, raw=True)` takes an unpreprocessed
block: if a `layer: preproc` model exists, every body line (after comment removal) is
first offered to it, with its own context stack starting at `main`; kinds, `multiline`,
`join`, `push`/`pop`/`set` behave exactly as for diagram rules. Matched lines are
consumed; the remaining lines form the body the diagram models see. Upstream
preprocesses the whole block before any factory runs (`BlockUmlBuilder.java:95`), so
this filter runs once per block. A block whose non-blank lines are all consumed is an
empty body. With `raw=False` (default; L2 input is already preprocessed) the preproc
model is ignored.

## Generated grammars (`dist/`)

`python -m tools.emit.build` writes the TextMate grammar from `model/`; two runs produce
byte-identical output.

| File | Notation | Consumers |
|---|---|---|
| `dist/plantuml.tmLanguage.json` | TextMate (`source.plantuml`), Oniguruma and PCRE | editors |
| `dist/plantuml.engine.json` | engine JSON (`engine_format` 1), ES2018 JavaScript regexes | `packages/engine` (see "TypeScript engine") |

Known limits, all intended and tested:

* **Java regex text.** The TextMate emitter keeps the model's Java regex text; only the
  interpreter translates it with `tools.model.java_regex` (see "Regex semantics").
* **The emitter drops `reject`, `emit: false`, `gives`/`needs` and `trim`.** It is wider
  than the interpreter for bodies that rely on those keys.
* **TextMate scope coverage is limited.** Generated class and sequence rules carry no
  scopes (the generated models give regexes no `scope`), so those bodies are matched but
  not highlighted. A start word no keyword covers (`@startjcckit`) is framed as an opaque
  block in which only comments and preprocessor lines are scoped.
* **Conditional factory `PSystemPathFactory`.** `eggs/PSystemPathFactory.java` (a
  `PSystemSingleLineFactory` accepting `path <alnum>`, `:49`) is added to the factory list
  only when the security profile is `INSECURE` (`PSystemBuilder.java:178-179`). The profile
  comes from `SecurityProfile.init()` (`security/SecurityProfile.java:114-134`): TeaVM
  builds are always `INSECURE`; otherwise the system property or environment variable
  `PLANTUML_SECURITY_PROFILE` (read by `SecurityUtils.getenv`,
  `security/SecurityUtils.java:202-212`) selects it, with `INSECURE` or its alias
  `UNSECURE`, and the default is `LEGACY`. The list is built once, when the `PSystemBuilder`
  singleton is created (`PSystemBuilder.java:128`, `:132-201`), so the profile in force at
  that moment decides for the whole JVM. The extractor and the oracle run the stock jar
  under the default profile, so the factory is absent from `extracted/`, from the `uml`
  `start_map` and from the models, and the jar rejects `@startuml` / `path abc` / `@enduml`
  (`tests/fixtures/single-line/neg/path.puml`). Supporting the `INSECURE` profile would
  need a single-line diagram model for `PSystemPathFactory`, listed in `start_map` right
  after `PSystemRIPFactory`; the model here describes the default profile only.

## TypeScript engine

`packages/engine` ports the interpreter to TypeScript. It reads no YAML: it runs
`dist/plantuml.engine.json` (`engine_format` 1), which `tools.emit.build` writes from the
resolved model with every regex already translated to JavaScript. Python is the reference.
The engine must equal it in `accepted`, `diagram`, `model`, `status` and `first_failure`,
and two checks enforce that: the conformance test (`packages/engine/test/conformance.test.ts`
against `tests/conformance/`) and the TS lane of the parity harness.

The core (`src/` except `cli.ts`, `pool.ts`, `worker.ts`) is ES2022 with no Node APIs, so
plantuml-ts can bundle it for browsers, VS Code and JetBrains JCEF; a fitness test
(`test/browser-safe.test.ts`) enforces this. Public API: `loadEngine(json)`,
`new Interpreter(engine, {startMap?, clock?})`, `interpreter.accepts(text, {raw?,
timeoutMs?})` and the cached `accepts(engine, text, opts)`.

### Regex translation (`tools/model/java_regex_js.py`)

The target is ES2018 regex with flag `u` (Chromium 64+, Safari 16.4+, Firefox 78+, so
JCEF 122 and every supported VS Code). Java semantics are kept as in "Regex semantics":

| Java construct | JavaScript emitted |
|---|---|
| `ci` (case-insensitive) | explicit ASCII folding (`[cC]`); never flag `i` |
| `(?i:…)`, `(?-i:…)`, `(?i)`, `(?-i)` | no modifier groups; they switch the translator's folding |
| `.` | `[^\n\r\x85  ]` |
| `\d \w \s \b` and POSIX `\p{…}` | the ASCII classes Java uses |
| `$`, `\Z` | `(?=LT?$)`, where LT is the Java line terminator |
| whole line `^…$` | `^(?:…)(?:\r\n\|(?<!\r)\n\|[\r\x85  ])?$` |
| `(?>X)` (atomic) | `(?=(?<_aN>X))\k<_aN>`, names unique per pattern |
| `X*+ X++ X?+ X{n,m}+` (possessive) | the atomic form of the greedy quantifier |
| `(?P<n>…)`, `(?P=n)` | `(?<n>…)`, `\k<n>` |
| named group never referenced | `(?:…)` (no duplicate group names) |
| class escapes | only escapes legal under `u` |

A fitness test over the engine JSON rejects modifier groups, duplicate group names and
`v`-flag class syntax. Caveats:

* **Atomic emulation backtracks differently.** The lookahead-plus-back-reference form
  commits to the same first match as a true atomic group, but V8 can still spend time
  re-entering the lookahead. The model's token and gap atomics are what keep its patterns
  linear: without them, the style join backtracks exponentially in V8. Never drop them.
* **Back references under `ci`** raise `JsRegexError` at build time: JS cannot fold a
  back reference to ASCII. The model has none.
* **`\k<n>` to a group that did not participate** matches empty in JS; Java and Python
  fail. Every model back reference targets a group that always participates first.
* **Numbered back references** raise `JsRegexError` in a pattern that also gets emulated
  atomic groups, because the added groups would shift the numbers.

### Recursion (`tools/model/js_subroutines.py`)

JavaScript has no `(?(DEFINE)…)`/`(?&name)`. The two packet conditionals were rewritten in
the YAML (see CHANGELOG). The other recursive patterns are inlined to a bounded depth per
pattern (observed nesting + 2, capped at 256 KB); deeper nesting does not match in JS, a
documented divergence that no fixture or corpus block reaches:

| Pattern | Depth | Expanded size |
|---|---|---|
| `RX_WELL_FORMED` | 8 | 259,635 B |
| `RX_BALANCED` | 8 | 4,125 B |
| `RX_EMPTY` | 3 | 485 B |
| other DEFINE patterns | `MAX_DEPTH` = 11 | |

The two JSON leaves (`CO_JSON_BLOCK_BODY`, `CO_JSON_DATA_INVALID`) nest 9 deep in the
corpora and grow about 4x per level, so no bounded expansion fits. The engine recognises
them natively (`src/native.ts`) at any depth. A line containing one is emitted as a
`split` (a sticky head regex, the native recognizer, a sticky tail regex), or an `any` of
alternatives, with a depth-4 `fast` regex whose answer is final in one direction. Detection
is keyed by the SHA-256 of each leaf's exact YAML source, so editing either leaf needs
`native.ts`, the digest table and `tests/model/test_native_json.py` updated together. The
engine JSON has no `unsupported` pattern; one would make every block reaching its context
`error`.

### Join early stop (`tools/model/js_prefix.py`)

`scan_join` stops a multi-line join early when no extension can match, using Python
`regex` partial matching, which JS lacks. Each join instead carries a *prefix-closure*
regex built from the Part tree: the prefix of a sequence is `p(a) | a p(b) | …`, of an
alternation the union of prefixes, of `X*` `X* p(X)`; a lookahead contributes `p(X)`
(Python reports partial when text ends inside a lookahead), lookbehinds are dropped, back
references and unanalysable leaves become `[^]*`, and a pattern over 64 KB falls back to
`^[^]*$`. The TS scan stops only when the prefix regex rejects, so verdicts never change. A
corpus-marked test checks that the prefix accepts every text Python's partial match accepts
(7.0M corpus texts, 0 violations).

### Guards (`tools/emit/guard.py`)

V8 compiles a regex on its first execution, at a cost that grows with its size, and
recompiles it to native code on the second. A few large patterns therefore dominate the
time to a first verdict (#4). Every whole-line, `split` or `any` pattern of at least 8 KB
gets a `guard` in the engine JSON when one helps: a regex of at most about 1 KB that every
line the pattern matches also matches. The engine tests the guard first and builds,
compiles and runs the pattern only for lines the guard passes, so a context pays for a
large pattern only when a line could match it.

A guard is built from the *head* of the Part: leading `seq` children (the last one may be
cut further), the alternation of every `alt` branch's head, or the head of a `plus` body.
`opt`, `star` and leaves are kept whole or not at all, a native JSON leaf never enters a
head, and a head that matches the empty string is dropped. Start and end patterns get
`^(?:H)`. A join prefix gets `prefix(H) | ^(?:H)`, since a prefix of a match either ends
inside the head or contains it. Verdicts do not change. Start guards agree with Python's
`fullmatch`; prefix guards accept everything Python's partial match accepts but reject part
of what the widened prefix regex alone accepted, so a join scan can stop sooner.
`tests/emit/test_guard.py` checks both on the fixtures and, marked `corpus`, the corpora.

`npm run bench -w packages/engine -- --patterns` reports load, first and second verdict
per diagram family in fresh processes, with the costliest patterns.

### Timeouts

`Deadline` is cooperative: it checks an injectable clock before every regex call and
throws `BlockTimeout`, which becomes status `timeout`. A single runaway regex inside the
library cannot be interrupted. The CLI's worker pool also kills a worker whose job runs
past `timeout_s` + 2 s, answers `timeout` for that job and respawns. V8 compiles each regex
on first execution, so loading (about 15 ms; nothing is compiled at load) says little about
the first verdict; see "Guards".

### Regenerate and run

```sh
uv run python -m tools.emit.build              # dist/plantuml.engine.json (and the TextMate grammar)
uv run python -m tools.validate.conformance    # tests/conformance goldens; --check reports drift
npm test -w packages/engine                    # tsc, vitest, conformance against the goldens
uv run python -m tools.validate.parity --corpus all --workers 4 --engine both
uv run python -m tools.validate.parity merge --corpus all --engine both
```

The CLI is `node packages/engine/dist/cli.js --engine dist/plantuml.engine.json
[--workers N]`: one `{"id", "text", "raw", "timeout_s"}` job per stdin line, one
`{"id", "verdict"}` line per job on stdout in input order, and JSON logs on stderr. The TS
lane builds `packages/engine` itself when `src/` is newer than `dist/cli.js`.

### TS engine troubleshooting

**A translator gap.** *Detection:* `tools.emit.build` fails with `JsRegexError` or a Node
compile error naming the pattern, the D2 fitness test fails, or the build prints an
`unsupported` pattern. *Mitigation:* extend `tools/model/java_regex_js.py` (or
`js_subroutines.py` for recursion) with a test against Node, or rewrite the model regex
into a form both engines take, keeping Python parity unchanged. Never leave an
`unsupported` pattern that a corpus block reaches.

**Engine divergence after a model change.** *Detection:* `tests/conformance` drifts
(`tools.validate.conformance --check` exits 1; regenerate when the Python change is
intended), the conformance test in `npm test` prints a mismatch table (fixture, block,
raw, field, python, ts), or `reports/engine-equality-<corpus>.json` has `mismatches > 0`.
*Mitigation:* regenerate `dist/` first, since a stale engine JSON is the common cause. Then
diagnose where TS first departs from Python (`tools/interp` is the reference) and fix the
TS module or the JS translator, never the Python side to match.

**A TS-only timeout.** *Detection:* a TS verdict has status `timeout` where Python's does
not, in the equality report or as a `warn` "worker killed" log line from the CLI.
*Mitigation:* find the pattern with the job's text; the usual cause is backtracking the
atomic emulation or a large bounded expansion makes costly in V8 (`RX_WELL_FORMED` is
465 KB of source). Tighten the model regex, or lower the pattern's depth if no corpus
block needs it, and confirm with the TS lane.

## Regenerating after an upstream bump

Everything under `extracted/`, `model/generated/` and `dist/` is a function of the pinned
upstream commit and the hand-written `model/`. To move the pin to a new commit `NEWSHA`
(prerequisites: the stock jar built from that commit, a PlantUML checkout containing it,
and the three corpora; see "Troubleshooting" for the environment variables):

1. **Pin.** Edit `upstream-pin.json` (`sha`, `version`), the only place the pin is stored
   (`tools/config.py` reads `PIN_SHA` from it for the default jar name and the provenance
   reader), then point `PLANTUML_JAR` at the new jar. The oracle cache key contains the sha,
   so cached verdicts of the old pin are not reused.
2. **Extract.** `uv run python -m tools.extract.build` compiles the Java harness against
   the jar; `uv run python -m tools.extract.run` rewrites `extracted/*.json` (one file per
   factory in `PSystemBuilder` order). Review `git diff extracted/`: added, removed or
   reordered commands show up here first.
3. **Translate.** `uv run python -m tools.translate.run` rewrites `model/generated/*.yaml`
   and reads the source text at `NEWSHA` through `git -C $PLANTUML_SRC show` for the
   `provenance.file:line` values. Never edit these files by hand.
4. **Check.** `uv run python -m tools.model.load --check model/` fails on a hand-written
   override, insert or provenance citation whose key no longer matches an entry; fix the
   family model that names it. Then `uv run pytest` (corpus tests re-resolve every
   citation in `model/` against the checkout; line numbers in hand-written models are
   re-verified by hand where they moved) and `uv run python -m tools.report.coverage` to
   regenerate `docs/coverage.md`: a command listed as `missing` is new upstream and needs a
   model rule or a documented exclusion in `reports/classify/*.yaml`.
5. **Build.** `uv run python -m tools.emit.build` rewrites `dist/`; run it twice and
   compare `shasum -a 256 dist/*`, and run `npm test` for the TextMate proof.
6. **Parity.** `uv run python -m tools.validate.parity --corpus all --workers 4`, then `uv run python -m tools.validate.parity merge --corpus all` and
   `uv run python -m tools.report.semantic_gaps`. Targets (D5): FR 0 on vega and
   plantuml-ts, at most 2% on pdiff with every case classified. Classify new FR/FA cases
   in `reports/classify/<family>.yaml` (`class: bug|semantic`, `note`, `cite`).
7. **TS engine.** `uv run python -m tools.validate.conformance` regenerates the
   conformance goldens (review the diff: it is the Python behaviour change), `npm test`
   checks the engine against them, and the TS lane (`--engine both` on the two parity
   commands) must report 0 Python/TS mismatches in `reports/engine-equality-*.json`, with
   TS FR/FA equal to Python's. See "TS engine troubleshooting".

## Troubleshooting

### An upstream bump breaks the extractor

*Detection.* `uv run python -m tools.extract.build` fails with `javac` errors (a class,
field or constructor the harness reads was renamed), or `tools.extract.run` throws a
reflection error naming the field (the harness reads fields of the command base classes
by declaring class, see the `Extract.java` header). A quieter form: a factory or command
vanishes from `extracted/` or moves to `unreachable`, which `git diff extracted/` and
`docs/coverage.md` (a `missing` row) show.

*Mitigation.* Keep the old pin until the harness is fixed; the old `extracted/` and
`model/generated/` stay valid for it. Fix the field reads in `tools/extract/*.java` (cite
the new `file:line`), rerun extract and translate, and add a case to `tests/extract` or
`tests/translate`. Do not patch `model/generated/` by hand to hide the change.

### The jar or the corpora are missing

*Detection.* Parity, oracle and corpus-marked tests exit with code 2 and
`<ENV> not found at <path>; set <ENV>` (`tools.config.ConfigError`).

| Variable | Default | Needed for |
|---|---|---|
| `PLANTUML_JAR` | `~/git/knowvah/plantuml-ts/oracle/dist/stock/plantuml-stock-<sha>.jar` | extract, oracle, parity, corpus tests |
| `PLANTUML_SRC` | `~/git/plantuml` | translate (provenance), citation tests |
| `CORPUS_VEGA` | `$PLANTUML_SRC/src/test/resources/vega` | parity `vega` |
| `CORPUS_PLANTUML_TS` | `~/git/knowvah/plantuml-ts/tests/corpus` | parity `plantuml-ts` |
| `CORPUS_PDIFF` | `~/git/pdiff` | parity `pdiff` |

*Mitigation.* Set the variables. Without them, everything that does not need the jar still
works: `uv run pytest -m "not corpus"`, `load --check`, `emit.build`, `npm test` and
`tools.report.coverage`. The jar is never committed; build or fetch the stock jar for the
pinned sha. Upstream line numbers cite the pin, so the checkout must contain it
(`git -C $PLANTUML_SRC cat-file -t 97a5992`); its `HEAD` may be a different branch.
