# @knowvah/plantuml-grammar
PlantUML syntax as data, generated from the command model in
[knowvah/plantuml-grammar](https://github.com/knowvah/plantuml-grammar):

- `plantuml.tmLanguage.json`: a TextMate grammar (scope `source.plantuml`) for editors and
  highlighters (VS Code, Shiki, vscode-textmate). Oniguruma and PCRE compatible.
- A TypeScript engine that judges whether a `@start...@end` block is valid PlantUML the
  way the PlantUML jar does, with the model it runs (`plantuml.engine.json`). Its core has
  no Node dependency: it runs in current browsers, VS Code and JetBrains IDEs from 2026.2.

Both are built from the same model at the same commit, so one version covers both.

**Status:** pre-release, built against PlantUML `97a5992` (`1.2026.8beta1`).

## Install
```sh
npm install @knowvah/plantuml-grammar
```

## TextMate grammar
In a VS Code extension, point `contributes.grammars` at the file in `node_modules` (or copy
it into the extension at build time):

```json
{
  "contributes": {
    "languages": [{ "id": "plantuml", "extensions": [".puml", ".plantuml"] }],
    "grammars": [
      {
        "language": "plantuml",
        "scopeName": "source.plantuml",
        "path": "./node_modules/@knowvah/plantuml-grammar/plantuml.tmLanguage.json"
      }
    ]
  }
}
```

With `vscode-textmate`:

```js
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import textmate from "vscode-textmate";

const require = createRequire(import.meta.url);
const file = require.resolve("@knowvah/plantuml-grammar/plantuml.tmLanguage.json");
const registry = new textmate.Registry({
  onigLib, // from vscode-oniguruma
  loadGrammar: async (scopeName) =>
    scopeName === "source.plantuml"
      ? textmate.parseRawGrammar(readFileSync(file, "utf8"), file)
      : null,
});
const grammar = await registry.loadGrammar("source.plantuml");
```

## Engine
`loadEngine` takes the parsed model; `accepts` judges one block.

```js
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { accepts, loadEngine } from "@knowvah/plantuml-grammar";

const require = createRequire(import.meta.url);
const model = JSON.parse(
  readFileSync(require.resolve("@knowvah/plantuml-grammar/plantuml.engine.json"), "utf8"),
);
const engine = loadEngine(model);

accepts(engine, "@startuml\nAlice -> Bob : hello\n@enduml");
// { accepted: true, diagram: "SEQUENCE", model: "sequence", status: "ok", firstFailure: null }

accepts(engine, "@startuml\n)(*&^\n@enduml");
// { accepted: false, ..., status: "reject", firstFailure: { line: 2, text: ")(*&^" } }
```

In a browser, fetch `plantuml.engine.json` and pass the parsed object to `loadEngine`. The
model is 4.4 MB (148 KB gzip). `Interpreter` reuses compiled rules across blocks; `accepts`
also takes `{ timeoutMs, raw }` (`raw: true` runs the preprocessor first).

## Versioning
Releases follow [Semantic Versioning](https://semver.org/). The public contracts are the
TextMate scope names, the engine JSON format (`engine_format`) and the engine API
(`loadEngine`, `Interpreter`, `accepts` and the `Verdict` type); changing any of them is a
major release. See the
[CHANGELOG](https://github.com/knowvah/plantuml-grammar/blob/main/CHANGELOG.md).

## License
MIT
