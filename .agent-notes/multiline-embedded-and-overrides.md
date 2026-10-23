## Observation: embedded `{{ ... }}` units hide end lines from a multiline scan
- **Finding**: `PSystemCommandFactory.java:288-307` glues a `{{ ... }}` embedded diagram
  (nested) into one unit and only tests a unit's last line against `end`, so `end note`
  or a lone `;` inside `{{ }}` does not close the outer command
  (`tools.interp.scan.unit_end`). Plain-line factories
  (`tools.interp.factories.NON_COMMAND_FACTORIES`, e.g. `JsonStyleStructure`) do not glue.
  An unclosed `{{` runs to the block end upstream.
- **Confidence**: High (interpreter source, toy tests)

## Observation: overrides hitting one entry under different keys merged in wrong order
- **Context**: `meta-diagrams-sprites` overrides `CommandSpriteSvg_26` while `common`
  overrides class name `CommandSpriteSvg`; both hit the same entry.
- **Finding**: `tools/model/patch.py:_refine` merged hits in scope order, so the included
  model's patch landed last and won, contrary to the module docstring. Only those two
  sprite entries ever get two hits. Fix kept in `git stash` ("override precedence fix")
  for branch `fix/override-precedence`.
- **Impact**: none on main today; matters once two keys hit one entry.
- **Confidence**: High (traced hit order; order-dependence scan over the whole model)

## Observation: pre-existing Pyright errors in tests/families/test_activity3.py
- **Finding**: lines 528-530 read `accepted`/`diagram_type` from the `BlockVerdict` TypedDict
  where those keys are NotRequired (reportTypedDictNotRequiredAccess). Not from this change.
- **Confidence**: High
- **Resolved** (chore/emit-cleanup): `BlockVerdict` is total but `error`; see emit-cleanup.md.
