## Observation: plantuml-plugins engine link points at a non-existent path
- **Context**: Architecture exploration of plantuml-grammar and sibling repos (2026-10-23)
- **Finding**: plantuml-plugins `packages/core/package.json` declares
  `link:../../../../plantuml-ts`. That resolves to `~/git/plantuml-ts`, but the checkout
  is at `~/git/knowvah/plantuml-ts`, so the installed symlink is dangling. The
  plantuml-plugins README still says to clone `github.com/sseely/plantuml-ts`.
- **Impact**: Any work that wires plantuml-grammar output into plantuml-plugins must fix
  or account for this link before plantuml-plugins builds will work.
- **Confidence**: High

## Observation: nothing consumes dist/plantuml.tmLanguage.json yet
- **Context**: Same exploration
- **Finding**:
  - plantuml-plugins VS Code ships a hand-written grammar: 110 lines, 14 rules, scope
    `source.plantuml`.
  - plantuml-ts `docs-site/.vitepress/plantuml.tmLanguage.ts` is a hand copy of that
    grammar.
  - Neither repo references plantuml-grammar.
  - The generated grammar is about 3.4 MB and uses the same scope name.
- **Impact**: The swap-in point is the grammar file alone, since the scopes match. Check
  the size and load time in the VS Code and Shiki hosts before adopting it.
- **Confidence**: High
