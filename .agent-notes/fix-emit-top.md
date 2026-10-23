## Observation: emitters emit top models only
- **Context**: sequence family left `gen-sequence-diagram` in dist.
- **Finding**: `tools/emit/tops.py:emitted_diagrams` keeps diagram-layer models that are a factory top or have no factory.
- **Impact**: a family's `remove`/narrowing now reaches TextMate.
- **Confidence**: High

