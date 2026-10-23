## Observation: semantic-gaps.md prose is generated from the report tool
- **Context**: fixing the stale counts PR #27 left in `docs/semantic-gaps.md`.
- **Finding**: the "Other parity differences" prose is `OTHER_NOTES` in
  `tools/report/semantic_gaps.py`; `python -m tools.report.semantic_gaps` rewrites the whole
  doc, so edits to the `.md` alone are lost and only the table follows the parity reports.
- **Impact**: after a parity run, update the counts in `OTHER_NOTES`, then regenerate.
- **Confidence**: High
