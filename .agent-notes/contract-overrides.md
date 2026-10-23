## Observation: class-name keys also match hand-written entries
- **Context**: Verifying the `class.yaml` worked example for overrides.
- **Finding**: A key equal to a simple `provenance.class` name matches every entry with that class,
  including hand-written entries of the refining model itself (they are patched too).
  A hand-written `class_body` rule citing `CommandCreateClassMultilines` as provenance was hit
  by an override keyed `CommandCreateClassMultilines` and failed schema validation (`push` + `pop`).
- **Impact**: Family authors citing an upstream class in provenance for a rule they write
  should key overrides by a unique `command` id, or cite a different class.
- **Confidence**: High

## Observation: patches apply per model, not inherited from resolved includes
- **Context**: Resolver design.
- **Finding**: `resolve_model` expands contexts from raw included models, so an included diagram
  model's `overrides` are re-collected and re-applied at the includer; an unmatched key there is
  an error (only keys whose winning declaration is a `layer: shared` model may match nothing).
- **Impact**: A family model that includes another family model (e.g. object includes class)
  needs the included model's override keys to match entries in the includer's resolved contexts.
- **Confidence**: High
