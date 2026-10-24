# Repository inventory

Snapshot 2026-10-23. Working trees as checked out locally: plantuml-grammar `main`
(c32400b), plantuml-ts `feat/sequence-divergence-drive-3` (86d1393), plantuml-plugins
`main` (5775254).

| Repo | Language | Runtime | Framework | Database | Key Deps | Entry | Notes |
|------|----------|---------|-----------|----------|----------|-------|-------|
| plantuml-grammar | Python; Java (extractor, oracle harness); JS (tests only) | Python >=3.11 (uv), Java 21, Node (unpinned) | — (pytest, ruff) | — | pyyaml 6.0.3, jsonschema 4.26.0, regex 2026.9.29; dev: pcre2 0.7.1, vscode-textmate 9.3.2, vscode-oniguruma 2.0.1 | `python -m tools.emit.build` (plus `tools.extract.*`, `tools.translate.run`, `tools.model.load`, `tools.validate.parity`, `tools.report.*`) | Pinned to PlantUML 97a5992 (1.2026.8beta1) |
| plantuml-ts | TypeScript; Java only in the external oracle build | Node >=26 (volta 26.9.0), TS ^6.0.3, Vite ^8.3.4, Vitest ^5.0.5 | VitePress 1.6.4 (docs-site) | — | @knowvah/dot-engine 2.4.0, elkjs 0.12.0, katex, pako, jsonc-parser, @xmldom/xmldom | `src/index.ts` (`renderSync`, `render`, `renderPages`, `renderAll`); npm `@knowvah/plantuml-ts@0.2.0` | Pure-SVG PlantUML port; owns the oracle jar and corpus |
| plantuml-plugins | TypeScript; Kotlin (JetBrains plugin) | Node >=22, pnpm 10 workspace, VS Code ^1.125.0, JetBrains 2025.2 | VitePress, Eleventy, Docusaurus, markdown-it, React, VS Code, JetBrains | — | @knowvah/plantuml-ts (link:), markdown-it, tsup ^8.5.1, esbuild ^0.28, vitest ^4.1.11, TS ^5.9.3 | `packages/core/src/index.ts`; `packages/vscode/src/extension.ts` | 8 packages; engine consumed via `link:` to a sibling checkout |

## Component summaries

### plantuml-grammar
1. A Java `Extract` program walks the command regexes of the pinned PlantUML jar and writes `extracted/*.json` (52 files).
2. `tools/translate` turns those trees into YAML command models in `model/generated/`, each rule citing the upstream `file:line`.
3. `tools/model` loads the generated and hand-written YAML, validates it against `model/schema.json`, and resolves includes, refs and patches.
4. Two consumers read the resolved model: `tools/interp`, an ordered first-match line interpreter, and `tools/emit`, which writes `dist/plantuml.tmLanguage.json`.
5. `tools/validate` runs the Java `Oracle` and the interpreter over three corpora and classifies each disagreement as FR or FA. `tools/report` writes the coverage and semantic-gap docs.

### plantuml-ts
1. `@knowvah/plantuml-ts` 0.2.0 renders PlantUML to SVG with no DOM, server or Java. Vite builds it to ESM and CJS.
2. The pipeline is: preprocessor (`src/core/tim`), block extraction, a diagram plugin's parse, then layout and SVG assembly.
3. Graph diagrams are laid out by `@knowvah/dot-engine`. ELK (`elkjs`) is optional and lazy-loaded. Sequence, gantt, mindmap and the other types use their own layout code.
4. `oracle/` builds a patched PlantUML jar from an external fork. Its stock jar and `tests/corpus` (4,401 files) are the parity inputs of plantuml-grammar.
5. The `packages/*` workspaces are stdlib, sprite and emoji asset packages. `docs-site` is a VitePress site with a playground and Shiki highlighting.

### plantuml-plugins
1. A pnpm monorepo of 8 packages, all at 0.1.0.
2. `@knowvah/plantuml-core` is the only package that imports the engine. It provides `renderAll` for Node, `renderDiagram` (sync) for browsers, and a `<plantuml-diagram>` web component.
3. `@knowvah/plantuml-markdown-it` renders fences and is reused by the VitePress, Eleventy and VS Code packages. Docusaurus uses remark/MDX together with the React package.
4. The VS Code extension renders in a `worker_threads` worker and previews in a webview. The JetBrains plugin (Kotlin) bundles the JS engine for JCEF.
5. The VS Code TextMate grammar (`source.plantuml`) is hand-written: 110 lines and 14 rules. Nothing generates it from plantuml-grammar.
