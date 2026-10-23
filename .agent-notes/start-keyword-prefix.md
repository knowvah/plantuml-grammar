## Observation: start keywords are a prefix test, and only TextMate had a word boundary
- **Finding**: `DiagramType.check` (core/DiagramType.java:220-232) compares the key against the
  text after `@start` as a prefix, ASCII-lowercased; `@startumlfoo` is `uml` (jar fixture
  `tests/fixtures/document/forms/name-suffix.puml`). The interpreter (`tools/interp/dispatch.py:lookup`)
  already used prefix semantics; TextMate added `(?![A-Za-z0-9])`.
  The 29 real `start_map` keys are prefix-free (tests/emit/test_framing.py).
- **Impact**: a new `start_map` key that prefixes another breaks this encoding; the prefix-free
  test fails first.
- **Confidence**: High

