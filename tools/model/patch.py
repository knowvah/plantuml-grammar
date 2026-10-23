"""Refine resolved contexts with ``overrides``, ``insert_before`` and ``insert_after``.

See docs/grammar-guide.md, "Refining generated models". Applied by the resolver to every
``layer: diagram`` model after its contexts are expanded: removes, then overrides, then
inserts. Patches are collected from the model and its transitive includes in scope order;
the first declaration of a key wins (the model's own beats an included one).
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from jsonschema import Draft202012Validator

from tools.model import Entry, Model, ModelError

if TYPE_CHECKING:
    from tools.model.resolve import _Resolver

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "model" / "schema.json"
DIAGRAM_LAYER = "diagram"
SHARED_LAYER = "shared"
OVERRIDES = "overrides"
INSERT_BEFORE = "insert_before"
INSERT_AFTER = "insert_after"
REMOVE = "remove"
REFINED_BY = "refined_by"
COMMAND_DEF = "#/$defs/command"
Contexts = dict[str, list[Entry]]


@lru_cache(maxsize=1)
def _command_validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    return Draft202012Validator({"$ref": COMMAND_DEF, "$defs": schema["$defs"]})


@dataclass(frozen=True)
class Declared:
    """A patch value with the model that declared it."""

    owner: str
    layer: str
    file: str
    pointer: str
    value: Any


Section = dict[str, Declared]


@dataclass(frozen=True)
class Plan:
    """Collected, ref-expanded patches for one target model."""

    overrides: Section
    before: Section
    after: Section

    @property
    def sections(self) -> dict[str, Section]:
        return {OVERRIDES: self.overrides, INSERT_BEFORE: self.before, INSERT_AFTER: self.after}


def simple_class_name(entry: Entry) -> str:
    """Simple name of ``provenance.class`` (after the last ``.``), ``$`` mapped to ``_``."""
    return str(entry["provenance"]["class"]).rsplit(".", 1)[-1].replace("$", "_")


def matches(entry: Entry, key: str) -> bool:
    """True when ``key`` is the entry's rule id or its provenance class simple name."""
    return entry["command"] == key or simple_class_name(entry) == key


def merge_override(entry: Entry, patch: Entry) -> Entry:
    """Shallow-merge ``patch`` over ``entry``; a ``None`` value deletes that key."""
    out = dict(entry)
    for key, value in patch.items():
        if value is None:
            out.pop(key, None)
        else:
            out[key] = value
    return out


def collect(models: dict[str, Model], scope: list[str], section: str) -> Section:
    """Patches of ``section`` over ``scope`` (model first); the first declaration of a key wins."""
    out: Section = {}
    for owner in scope:
        model = models[owner]
        file = str(model.path) if model.path else model.id
        for key, value in getattr(model, section).items():
            pointer = f"/{section}/{key}"
            out.setdefault(key, Declared(owner, model.layer, file, pointer, value))
    return out


def _fail(decl: Declared, message: str, suffix: str = "") -> ModelError:
    return ModelError(message, decl.file, decl.pointer + suffix)


def _expand_override(resolver: _Resolver, mid: str, decl: Declared) -> Declared:
    patch: Entry = decl.value
    if patch.get(REMOVE):
        return decl
    out = resolver.expand_entry_parts(decl.owner, patch, decl.pointer)
    key = resolver.missing_transition(mid, out)
    if key:
        raise _fail(decl, f"unknown context '{out[key]}'", f"/{key}")
    return replace(decl, value=out)


def _expand_inserts(resolver: _Resolver, mid: str, decl: Declared) -> Declared:
    entries: list[Entry] = []
    for index, raw in enumerate(decl.value):
        pointer = f"{decl.pointer}/{index}"
        entry = resolver.expand_entry_parts(decl.owner, raw, pointer)
        key = resolver.missing_transition(mid, entry)
        if key:
            raise _fail(decl, f"unknown context '{entry[key]}'", f"/{index}/{key}")
        entries.append(entry)
    return replace(decl, value=entries)


def _expanded(section: Section, expand: Callable[[Declared], Declared]) -> Section:
    return {key: expand(decl) for key, decl in section.items()}


def build_plan(resolver: _Resolver, models: dict[str, Model], mid: str) -> Plan:
    """Collect and ref-expand every patch visible from ``mid``."""
    scope = resolver.scope(mid)
    return Plan(
        _expanded(collect(models, scope, OVERRIDES), lambda d: _expand_override(resolver, mid, d)),
        _expanded(
            collect(models, scope, INSERT_BEFORE), lambda d: _expand_inserts(resolver, mid, d)
        ),
        _expanded(
            collect(models, scope, INSERT_AFTER), lambda d: _expand_inserts(resolver, mid, d)
        ),
    )


def _hits(
    section: Section, entry: Entry, name: str, matched: set[tuple[str, str]]
) -> list[Declared]:
    found = [decl for key, decl in section.items() if matches(entry, key)]
    matched.update((name, key) for key in section if matches(entry, key))
    return found


def _refine(entry: Entry, hits: list[Declared]) -> Entry:
    """Apply the matching overrides, scope-first last so the model's own beats an included
    one where different keys hit one entry; the result is schema-validated."""
    merged = entry
    for decl in reversed(hits):
        merged = merge_override(merged, decl.value)
    merged[REFINED_BY] = hits[0].owner
    errors = sorted(e.message for e in _command_validator().iter_errors(merged))
    if errors:
        raise _fail(
            hits[0], f"override yields an invalid entry for '{entry['command']}': {errors[0]}"
        )
    return merged


def _patch_entry(plan: Plan, entry: Entry, matched: set[tuple[str, str]]) -> list[Entry]:
    hits = _hits(plan.overrides, entry, OVERRIDES, matched)
    before = _hits(plan.before, entry, INSERT_BEFORE, matched)
    after = _hits(plan.after, entry, INSERT_AFTER, matched)
    if any(decl.value.get(REMOVE) for decl in hits):
        for decl in [*before, *after]:
            raise _fail(decl, f"insert relative to removed entry '{entry['command']}'")
        return []
    refined = _refine(entry, hits) if hits else entry
    return [
        *(e for decl in before for e in decl.value),
        refined,
        *(e for decl in after for e in decl.value),
    ]


def _check_matched(plan: Plan, matched: set[tuple[str, str]]) -> None:
    for name, section in plan.sections.items():
        for key, decl in section.items():
            if (name, key) not in matched and decl.layer != SHARED_LAYER:
                raise _fail(decl, f"{name} key '{key}' matches no entry")


def apply_patches(
    resolver: _Resolver, models: dict[str, Model], mid: str, contexts: Contexts
) -> Contexts:
    """Return ``contexts`` refined by the patches visible from ``mid``.

    Only ``layer: diagram`` models are patched; a shared model's own patches do not apply
    to itself. Raises ``ModelError`` for unmatched keys (unless declared by a shared model),
    invalid merged entries and inserts relative to removed entries.
    """
    if models[mid].layer != DIAGRAM_LAYER:
        return contexts
    plan = build_plan(resolver, models, mid)
    matched: set[tuple[str, str]] = set()
    out = {
        name: [e for entry in entries for e in _patch_entry(plan, entry, matched)]
        for name, entries in contexts.items()
    }
    _check_matched(plan, matched)
    return out
