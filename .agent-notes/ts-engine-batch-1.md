## Observation: `\-` outside a class is a SyntaxError under the JS `u` flag
- **Context**: T2 Java→JS translator, literal writer
- **Finding**: Under `u`, identity escapes outside a class are only legal for syntax
  characters: `\_ \" \' \ ` and `\-` all throw. Inside a class `\-` is fine. So
  `literal_to_js("Ab-", ci=True)` is `[aA][bB]-`, not `[aA][bB]\-` as the T2 brief said.
- **Impact**: Any JS writer must track whether it is inside a class before escaping `-`.
- **Confidence**: High (checked in Node)

## Observation: Java numbers named groups, so demoting them can shift `\N`
- **Context**: T2 named-group demotion
- **Finding**: A named group counts toward Java's numeric group numbers. When a pattern
  has a numeric back reference, `java_regex_js` keeps named groups as plain `(` instead of
  `(?:` so that later numbers do not shift.
- **Impact**: T5 and any later AST rewrite (T9 inlining) must keep group numbering stable.
- **Confidence**: High

## Observation: `java_regex_js` imports private helpers from `java_regex`
- **Context**: T2 reuse of the Python translator's parser pieces
- **Finding**: It imports `_GROUP`, `_PROPERTY`, `_class_atom`, `_class_range`,
  `_property`, `_hex_escape`, `_apply_flags`, `_fold`, `_single`, `_set_base`,
  `_is_ascii_letter` from `tools/model/java_regex.py`.
- **Impact**: Renaming those in the reference translator breaks the JS translator.
- **Confidence**: High

## Observation: one model leaf needs T5's possessive emulation; packet now uses `(?P=`
- **Context**: T2 model-wide compile test
- **Finding**: The only possessive quantifier in the model is `*+` in
  `model/diagrams/meta-diagrams-ebnf.yaml:58`. After T3, `PK_ZERO_FIELD` and
  `PK_NONZERO_FIELD` each hold 63 `(?P=pkzp)`/`(?P=pknp)` back references (not under ci).
  177 of the 1,092 JRE vectors use possessive quantifiers.
- **Impact**: T5 must translate these; its tests should drop the T2 `(T5)` skips.
- **Confidence**: High

## Observation: family-filtered parity drops `disagree` from an empty corpus report
- **Context**: T3 `tools.validate.parity --family nwdiag-packet`
- **Finding**: With `--family`, the plantuml-ts report (0 blocks for the family) is
  rewritten without the `totals.disagree` key, so the committed file shows a one-line
  diff even though the counts are equal.
- **Impact**: Restore that file after family-filtered runs; it is not a count change.
- **Confidence**: Medium (seen once)

## Observation: Volta honours the root `package.json` pin
- **Context**: T4 scaffold
- **Finding**: With `"volta": {"node": "26.9.0"}`, `node --version` in the repo prints
  v26.9.0 (global default stays 25.2.1). vitest 5.0.5, TypeScript 6 and `@types/node`
  ^26 install cleanly as workspace dev dependencies.
- **Impact**: Run Node commands from inside the repo to get Node 26.
- **Confidence**: High
