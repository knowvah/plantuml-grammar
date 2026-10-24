// Public API of the engine (contract C7, plans/ts-engine/contracts.md#c7). Browser-safe
// (D6): nothing Node-only is exported or imported.
export { Interpreter, accepts } from "./engine.js";
export type { AcceptsOptions, CachedAcceptsOptions, InterpreterOptions } from "./engine.js";
export { loadEngine } from "./load.js";
export type { EngineModel } from "./load.js";
export type { FirstFailure, Status, Verdict } from "./types.js";
