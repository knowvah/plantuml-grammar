## Observation: a start directive never appears inside a block body
- **Finding**: `BlockUmlBuilder.java:101-102` starts a new block at every start line, so
  `UmlSource.isEmpty`'s start-directive skip only ever skips line 1. The interpreter's
  `_is_empty` (trimmed lines only) is therefore exact.
- **Confidence**: High (source read)
