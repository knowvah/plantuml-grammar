## Observation: DEFINE/subroutine expansion grows about 4x per level for JSON
- **Context**: T9 bounded expansion of `(?(DEFINE)…)(?&name)` for JavaScript
- **Finding**: Nesting `k` arrays or objects needs `k+1` activations of `jv`; with two
  `(?&jv)` references per level the JSON definitions grow about 4x per level, so the
  corpus depth (9) would be ~140 MB. RX_WELL_FORMED and RX_BALANCED reach depth 6 only
  through two long "as"-clause entity lines. Size limits are in UTF-8 bytes, which
  differ from char counts for RX_WELL_FORMED (non-ASCII text). `(?!)` must be emitted as
  `(?:(?!))` because `u` mode rejects a quantified lookahead and the model has `(?&a)?`.
  Expansion skips escapes and `[...]` but does not recognise `\Q…\E` (no DEFINE pattern
  uses it).
- **Impact**: Why the two JSON leaves are native in TS (D3a). Do not raise depth caps
  hoping to fit them.
- **Confidence**: High

## Observation: the JSON leaves are not standard JSON
- **Context**: T9b native recognizers in `packages/engine/src/native.ts`
- **Finding**: Both leaves allow U+E100 inside numbers and literals. The block-body leaf
  also matches a bare member list (`"a":1,"b":2`); every pair boundary and whitespace
  prefix is a valid end, and a lone string is a valid root end. In
  CO_JSON_DATA_INVALID, `(?!.)` means end of string or next char is a Java line
  terminator. The object-key lookahead `Q(?:\\Q|[^Q])+Q` is ambiguous (a backslash
  before a quote may be a lone unit), so reachable closing quotes are tracked as a set.
  Inside a container only the longest number end can continue, which keeps the block
  body linear.
- **Impact**: Any change to those YAML leaves must be mirrored in `native.ts`; the proof
  is `tests/model/test_native_json.py`.
- **Confidence**: High

## Observation: a raw RegExp satisfies the Matcher interface
- **Context**: T9b `Matcher` (C8)
- **Finding**: `RegExp.test(text, deadline)` type-checks against `Matcher` and silently
  ignores the deadline. Sticky `/uy` patterns need `lastIndex` set before every `test`;
  a successful `test` leaves it advanced.
- **Impact**: T13 and later must take matchers only from `engine.matcher(id)`; never pass
  `engine.pattern(id)` to scan or rule code.
- **Confidence**: High

## Observation: Python `regex` partial matching and lookaheads
- **Context**: T10 prefix-closure sweep
- **Finding**: `fullmatch(text, partial=True)` is true whenever the text ends inside a
  lookahead (positive or negative), whatever follows it in the pattern. A JS
  replacement must over-approximate this; dropping lookaheads alone missed 5,138 EBNF
  texts.
- **Impact**: Any future JS stand-in for Python partial matching.
- **Confidence**: High

## Observation: atomic groups are what keep model patterns linear in Node
- **Context**: T10, widening atomics to plain greedy groups
- **Finding**: Without the model's token/gap atomics, the style join backtracks
  exponentially in V8 (9 tokens took 4.6 s; one sample did not finish in 300 s). The
  T5 emulation `(?=(?<_aN>X))\k<_aN>` needs globally unique `_aN` names; composing
  Parts' `to_js` output naively throws "Duplicate capture group name".
  `js_prefix._number_atomics` renumbers them. V8 can also throw `RangeError` (stack
  overflow) on long backtracking.
- **Impact**: T12's emitter must renumber `_aN` across each composed pattern. The TS
  scanner should treat a throwing prefix `test()` as "keep scanning".
- **Confidence**: High

## Observation: corpus sweep cost is in a few long joins
- **Context**: T10 corpus sweep
- **Finding**: 344 join entries collapse to 18 distinct join variants. Cost is Python
  partial matching on long uncapped joins (EBNF, Files*); one 45,510-line body held a
  worker for ~10 min until large files were split by start index. The corpus sweep
  takes ~26 min on 12 processes and runs in the full pytest gate.
  `resolve(load_dir("model"))` now takes about 13 s.
- **Impact**: Budget the full pytest gate at ~50 min from batch 3 on.
- **Confidence**: High

## Observation: scanBracket depth can go below zero only in a glued group
- **Context**: T11 port of `scan.py`
- **Finding**: `scanBracket` starts at depth 1 and counts only lines after the start
  line; the between-unit check stops at 0, so negative depth is reachable only inside
  one glued `{{ … }}` group (e.g. `{{`, `}`, `}`, `}}` after `a {`). Matches Python.
  `loadEngine` requires `join.prefix`, so the no-prefix fallback is unreachable.
- **Impact**: Do not "fix" the negative-depth case; it is reference behaviour.
- **Confidence**: High

## Observation: shell gotchas seen by agents
- **Context**: Batch 3 tooling
- **Finding**: macOS `sed -i` needs a suffix argument (`sed -i ''`) or it fails, and
  inside `&&` chains it stops the chain. U+E100/U+E121 are invisible in terminal
  output, and escapes written through Python heredocs can turn into raw characters.
- **Impact**: Inspect joiner-bearing strings with `repr()` or hex dumps.
- **Confidence**: High
