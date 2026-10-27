"""Emit ``dist/plantuml.engine.json``: the resolved model with JavaScript regexes (C1, C1a).

Every pattern is a whole-line JS regex built like ``tools/interp/compile.py:31-53`` builds the
Python one (``line_pattern`` there, ``line_pattern_js`` here), with the translators of
``tools.model.java_regex_js``, ``js_subroutines`` (C3, C3a) and ``js_prefix`` (C4). A Part that
holds a native JSON leaf (D3a) is distributed over ``opt``/``alt`` and emitted as ``split``
patterns (sticky head and tail around the native recognizer) inside an ``any``. Decisions D1,
D3, D3a, D4 and D7: ``plans/ts-engine/decisions.md``.
"""

from __future__ import annotations

import gzip
import json
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from functools import reduce
from pathlib import Path
from typing import Any

from tools.emit.guard import GUARD_MIN_BYTES, guard_head, prefix_guard, start_guard
from tools.interp.compile import LIST_JOINERS, QUANTIFIERS, part_key
from tools.interp.factories import NON_COMMAND_FACTORIES
from tools.model import Entry, Part, ResolvedModels
from tools.model.java_regex_js import (
    LINE_TERMINATOR,
    JsRegexError,
    line_pattern_js,
    literal_to_js,
    to_js,
)
from tools.model.js_prefix import TOP_PATTERN, PrefixError, _number_atomics, prefix_pattern
from tools.model.js_subroutines import (
    Unsupported,
    expand_subroutines,
    fast_depth,
    fast_final,
    native_kind,
)
from tools.model.load import load_dir
from tools.model.resolve import resolve, top_models

ROOT = Path(__file__).resolve().parents[2]
PIN_PATH = ROOT / "upstream-pin.json"
ENGINE_FORMAT = 1
PATTERN_FLAGS = "u"
STICKY_FLAGS = "uy"
ENCODING = "utf-8"
MAX_ALTERNATIVES = 16
MAX_BYTES = 10 * 1024 * 1024
MAX_LOAD_MS = 1000.0
NODE_TIMEOUT_S = 300
DIAGRAM_LAYER = "diagram"
MAIN_CONTEXT = "main"
ATOM_OPEN_NAME = "(?<_a@o>"
ATOM_CLOSE_REF = "\\k<_a@c>"
_ATOM_NAMES = re.compile(r"(\\k<_a\d+>)|(\(\?<_a\d+>)|\\.", re.DOTALL)
_HEAD_TAIL_FORBIDDEN = re.compile(r"(\\k<)|(\(\?<_a)|\\.", re.DOTALL)
NODE_SCRIPT = """
const fs = require("fs");
const t0 = process.hrtime.bigint();
const engine = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
const wanted = new Set();
const visit = (id) => {
  if (wanted.has(id)) return;
  wanted.add(id);
  const p = engine.patterns[id];
  if (p.split) [p.split.head, p.split.tail, p.split.fast].forEach((m) => m !== null && visit(m));
  if (p.any) p.any.forEach(visit);
};
for (const id of engine.model_order) {
  const m = engine.models[id];
  if (m.layer !== "diagram" || m.contexts.main === undefined) continue;
  for (const e of engine.context_table[m.contexts.main]) {
    visit(e.start);
    if (e.end !== undefined) visit(e.end);
    if (e.join) visit(e.join.prefix);
  }
}
const compiled = [];
const compile = (p) => (p.source === undefined ? null : new RegExp(p.source, p.flags));
for (const id of wanted) compiled.push(compile(engine.patterns[id]));
const loadMs = Number(process.hrtime.bigint() - t0) / 1e6;
const t1 = process.hrtime.bigint();
for (const re of compiled) if (re) { re.lastIndex = 0; try { re.test(""); } catch (e) {} }
const execMs = Number(process.hrtime.bigint() - t1) / 1e6;
const failures = [];
engine.patterns.forEach((p, id) => {
  try { compile(p); } catch (e) { failures.push([id, String(e)]); }
});
process.stdout.write(JSON.stringify({ loadMs, execMs, wanted: wanted.size, failures }));
"""


class EngineBuildError(Exception):
    """The engine cannot be built: a contract violation, or a pattern that does not compile."""


# --- Part -> JS source ---------------------------------------------------------------------


def _placeholder_atomics(source: str) -> str:
    """Turn a leaf's ``_aN`` names into the placeholders ``js_prefix._number_atomics`` numbers."""

    def swap(found: re.Match[str]) -> str:
        if found.group(1):
            return ATOM_CLOSE_REF
        return ATOM_OPEN_NAME if found.group(2) else found.group(0)

    return _ATOM_NAMES.sub(swap, source)


def _leaf_js(part: Part) -> str:
    ci = bool(part.get("ci"))
    if "regex" in part:
        source = str(part["regex"])
        depth = fast_depth(source) if native_kind(source) is not None else None
        if native_kind(source) is not None and depth is None:
            raise EngineBuildError("a native leaf without a fast regex has no JavaScript form")
        return to_js(expand_subroutines(source, depth), ci=ci)
    if "literal" in part:
        return literal_to_js(str(part["literal"]), ci=ci)
    raise EngineBuildError(f"unresolved or unknown Part: {sorted(part)}")


def _raw_js(part: Part, memo: dict[int, tuple[Part, str]]) -> str:
    """Like ``compile.part_to_regex`` in JS; atomic names are placeholders until numbered."""
    cached = memo.get(id(part))
    if cached is not None:
        return cached[1]
    text = _compose_js(part, memo)
    memo[id(part)] = (part, text)
    return text


def _compose_js(part: Part, memo: dict[int, tuple[Part, str]]) -> str:
    for key, joiner in LIST_JOINERS.items():
        if key in part:
            return "(?:" + joiner.join(_raw_js(p, memo) for p in part[key]) + ")"
    for key, quantifier in QUANTIFIERS.items():
        if key in part:
            return "(?:" + _raw_js(part[key], memo) + ")" + quantifier
    return "(?:" + _placeholder_atomics(_leaf_js(part)) + ")"


def part_to_js(part: Part) -> str:
    """The JS body of ``part`` (no anchors), with unique emulated-atomic names."""
    return _number_atomics(_raw_js(part, {}))


def _check_head_tail(source: str, role: str) -> None:
    for found in _HEAD_TAIL_FORBIDDEN.finditer(source):
        if found.group(1) or found.group(2):
            raise EngineBuildError(
                f"split {role} contains an emulated atomic group or a back reference "
                f"(JS evaluates lookbehind right to left): {found.group(0)}"
            )


# --- native leaf distribution (D3a) --------------------------------------------------------


def _is_native(part: Part) -> bool:
    return "regex" in part and native_kind(str(part["regex"])) is not None


def _has_native(part: Part) -> bool:
    for key in (*LIST_JOINERS, *QUANTIFIERS):
        if key in part:
            children = part[key] if key in LIST_JOINERS else [part[key]]
            return any(_has_native(child) for child in children)
    return _is_native(part)


def _product(options: list[list[list[Part]]]) -> list[list[Part]]:
    return reduce(lambda acc, nxt: [a + b for a in acc for b in nxt], options, [[]])


def _alternatives(part: Part) -> list[list[Part]]:
    """Flat part lists whose union is ``part``; native-free subtrees stay whole."""
    if not _has_native(part):
        return [[part]]
    if "seq" in part:
        return _product([_alternatives(child) for child in part["seq"]])
    if "alt" in part:
        return [option for child in part["alt"] for option in _alternatives(child)]
    if "opt" in part:
        return [[], *_alternatives(part["opt"])]
    if "regex" in part:
        return [[part]]
    raise EngineBuildError("a native JSON leaf under star or plus cannot be split")


# --- the pattern and context tables --------------------------------------------------------


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


class _Table:
    """Deduplicated list: ``add`` returns the index of an equal earlier item."""

    def __init__(self) -> None:
        self.items: list[Any] = []
        self._index: dict[str, int] = {}

    def add(self, item: Any) -> int:
        key = _dumps(item)
        if key not in self._index:
            self._index[key] = len(self.items)
            self.items.append(item)
        return self._index[key]


class _Builder:
    def __init__(self) -> None:
        self.patterns = _Table()
        self.contexts = _Table()
        self._parts: dict[str, int] = {}
        self._prefixes: dict[str, int] = {}
        self._memo: dict[int, tuple[Part, str]] = {}

    def _plain(self, parts: list[Part]) -> int:
        body = _raw_js(parts[0], self._memo) if len(parts) == 1 else self._joined(parts)
        source = line_pattern_js(_number_atomics(body))
        return self.patterns.add({"source": source, "flags": PATTERN_FLAGS})

    def _joined(self, parts: list[Part]) -> str:
        return "(?:" + "".join(_raw_js(p, self._memo) for p in parts) + ")"

    def _split(self, parts: list[Part]) -> int:
        at = next(i for i, p in enumerate(parts) if _is_native(p))
        if any(_is_native(p) for p in parts[at + 1 :]):
            raise EngineBuildError("an alternative holds more than one native JSON leaf")
        leaf = parts[at]
        head = f"(?<=^(?:{_number_atomics(self._joined(parts[:at]))}))"
        tail = f"(?:{_number_atomics(self._joined(parts[at + 1 :]))}){LINE_TERMINATOR}?$"
        _check_head_tail(head, "head")
        _check_head_tail(tail, "tail")
        kind = native_kind(str(leaf["regex"]))
        split = {
            "head": self.patterns.add({"source": head, "flags": STICKY_FLAGS}),
            "tail": self.patterns.add({"source": tail, "flags": STICKY_FLAGS}),
            "native": kind,
            "fast": None if fast_depth(str(leaf["regex"])) is None else self._plain(parts),
            "fast_final": fast_final(str(leaf["regex"])),
        }
        return self.patterns.add({"split": split})

    def _build(self, part: Part) -> int:
        if not _has_native(part):
            return self._plain([part])
        ids = [
            self._split(alt) if any(_is_native(p) for p in alt) else self._plain(alt)
            for alt in _alternatives(part)
        ]
        return ids[0] if len(ids) == 1 else self.patterns.add({"any": ids})

    def pattern_id(self, part: Part) -> int:
        """Pattern id of the whole-line pattern of ``part``; ``unsupported`` on a JS limit."""
        key = part_key(part)
        if key not in self._parts:
            ident = self._guarded(lambda: self._build(part))
            self._add_guard(ident, part, lambda _head, js: start_guard(js))
            self._parts[key] = ident
        return self._parts[key]

    def prefix_id(self, part: Part, command: str) -> int:
        key = part_key(part)
        if key not in self._prefixes:
            ident = self._guarded(
                lambda: self.patterns.add(
                    {"source": prefix_pattern(part, command), "flags": PATTERN_FLAGS}
                )
            )
            self._add_guard(ident, part, lambda head, js: self._prefix_guard(head, js, command))
            self._prefixes[key] = ident
        return self._prefixes[key]

    def _add_guard(self, ident: int, part: Part, make: Callable[[Part, str], str | None]) -> None:
        """Put a guard (``tools.emit.guard``) on a large pattern that has none yet."""
        item = self.patterns.items[ident]
        if "unsupported" in item or "guard" in item or self._bytes(item) < GUARD_MIN_BYTES:
            return
        head = guard_head(part, lambda p: _raw_js(p, self._memo), _is_native)
        if head is None:
            return
        guard = make(head, _number_atomics(_raw_js(head, self._memo)))
        if guard is not None:
            item["guard"] = guard

    def _prefix_guard(self, head: Part, head_js: str, command: str) -> str | None:
        head_prefix = prefix_pattern(head, command)
        return None if head_prefix == TOP_PATTERN else prefix_guard(head_prefix, head_js)

    def _bytes(self, item: dict[str, Any]) -> int:
        """UTF-8 size of a pattern's regex sources, members included."""
        if "source" in item:
            return len(str(item["source"]).encode(ENCODING))
        if "any" in item:
            return sum(self._bytes(self.patterns.items[i]) for i in item["any"])
        split = item["split"]
        parts = [split["head"], split["tail"]] + ([] if split["fast"] is None else [split["fast"]])
        return sum(self._bytes(self.patterns.items[i]) for i in parts)

    def _guarded(self, make: Callable[[], int]) -> int:
        try:
            return make()
        except (JsRegexError, Unsupported, PrefixError) as error:
            return self.patterns.add({"unsupported": str(error)})

    def entry(self, entry: Entry) -> dict[str, Any]:
        action, target = "", ""
        if entry.get("pop"):
            action = "pop"
        for key in ("push", "set"):
            if key in entry:
                action, target = key, entry[key]
        out: dict[str, Any] = {
            "command": entry["command"],
            "kind": entry["kind"],
            "start": self.pattern_id(entry["parts"]),
            "action": action,
            "target": target,
            "require_pop": bool(entry.get("require_pop")),
            "reject": bool(entry.get("reject")),
            "gives": entry.get("gives", ""),
            "needs": entry.get("needs", ""),
            "untrimmed": entry.get("trim") is False,
        }
        if entry.get("end") is not None:
            out["end"] = self.pattern_id(entry["end"])
        if "join" in entry:
            prefix = self.prefix_id(entry["parts"], entry["command"])
            out["join"] = {"max_lines": entry["join"]["max_lines"], "prefix": prefix}
        return out

    def context(self, entries: list[Entry]) -> int:
        return self.contexts.add([self.entry(e) for e in entries])


def build_engine(models: ResolvedModels, pin: str) -> dict[str, Any]:
    """The engine JSON object (C1/C1a) for ``models``; ``pin`` is the upstream sha."""
    builder = _Builder()
    out_models: dict[str, Any] = {}
    for mid, model in models.items():
        out_models[mid] = {
            "layer": model.layer,
            "diagram": model.diagram,
            "factory": model.factory,
            "glue_units": model.factory not in NON_COMMAND_FACTORIES,
            "empty_needs_end": model.empty_needs_end,
            "start_map": {k: list(v) for k, v in model.start_map.items()},
            "includes": list(model.includes),
            "contexts": {name: builder.context(es) for name, es in model.contexts.items()},
        }
    return {
        "engine_format": ENGINE_FORMAT,
        "pin": pin,
        "patterns": builder.patterns.items,
        "context_table": builder.contexts.items,
        "models": out_models,
        "model_order": list(models),
        "tops": top_models(models),
    }


def render_engine(models: ResolvedModels, pin: str) -> str:
    """``build_engine`` serialised deterministically, with a trailing newline."""
    return _dumps(build_engine(models, pin)) + "\n"


def read_pin(path: Path = PIN_PATH) -> str:
    """The upstream sha from ``upstream-pin.json``."""
    return str(json.loads(path.read_text(encoding=ENCODING))["sha"])


def emit_engine_json(resolved: ResolvedModels) -> str:
    """Emitter entry point for ``tools.emit.build``."""
    return render_engine(resolved, read_pin())


def write_engine(path: Path, models: ResolvedModels | None = None) -> None:
    """Write the engine JSON to ``path``; loads and resolves ``model/`` when no models given."""
    resolved = models if models is not None else resolve(load_dir(ROOT / "model"))
    path.write_text(emit_engine_json(resolved), encoding=ENCODING, newline="\n")


# --- build-time checks and report ----------------------------------------------------------


@dataclass(frozen=True)
class Probe:
    """Result of the Node compile-and-load probe."""

    load_ms: float
    exec_ms: float
    loaded_patterns: int
    failures: list[tuple[int, str]]


def probe_engine(path: Path) -> Probe:
    """Compile every pattern in Node and time the load of all diagram ``main`` contexts."""
    node = shutil.which("node")
    if node is None:
        raise EngineBuildError("node is not on PATH; the engine build gate needs Node.js")
    done = subprocess.run(  # noqa: S603 - fixed argv, trusted local file
        [node, "-e", NODE_SCRIPT, str(path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=NODE_TIMEOUT_S,
    )
    if done.returncode != 0:
        raise EngineBuildError(f"node probe failed: {done.stderr.strip()[:500]}")
    data = json.loads(done.stdout)
    failures = [(int(i), str(e)) for i, e in data["failures"]]
    return Probe(data["loadMs"], data["execMs"], data["wanted"], failures)


def report_engine(path: Path) -> None:
    """Print size, counts, unsupported list and cold-load time; raise on a broken build."""
    raw = path.read_bytes()
    data = json.loads(raw)
    unsupported = [
        (i, p["unsupported"]) for i, p in enumerate(data["patterns"]) if "unsupported" in p
    ]
    probe = probe_engine(path)
    gz = len(gzip.compress(raw, mtime=0))
    print(f"engine json: {len(raw)} bytes raw, {gz} bytes gzip")
    print(f"patterns: {len(data['patterns'])}, contexts: {len(data['context_table'])}")
    print(f"unsupported: {len(unsupported)}")
    for ident, reason in unsupported:
        print(f"  pattern {ident}: {reason}")
    print(
        f"cold load (parse + new RegExp of {probe.loaded_patterns} main patterns): "
        f"{probe.load_ms:.0f} ms; first exec of them: {probe.exec_ms:.0f} ms"
    )
    if probe.failures:
        lines = [f"pattern {i}: {e}" for i, e in probe.failures[:10]]
        raise EngineBuildError("patterns do not compile in Node:\n" + "\n".join(lines))
    if len(raw) > MAX_BYTES or probe.load_ms > MAX_LOAD_MS:
        raise EngineBuildError(f"engine over budget: {len(raw)} bytes, {probe.load_ms:.0f} ms")
