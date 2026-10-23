"""Hoist subtrees repeated across commands into ``variables`` with ``ref`` placeholders.

A subtree qualifies when it occurs in at least ``MIN_COMMANDS`` distinct commands and is
heavy enough (``MIN_WEIGHT`` characters of pattern text) to be worth naming. Larger
subtrees are hoisted first, so a shared URL parser becomes one variable whose own
definition may reference smaller shared variables. A variable used by commands of a
single model is owned by that model; one used by several (directly or through another
variable) is owned by ``None`` and belongs in the shared model.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field

from tools.model import Part

MIN_COMMANDS = 3
MIN_WEIGHT = 40
FALLBACK_NAME = "COMMON"
_LIST_KEYS = ("seq", "alt")
_UNARY_KEYS = ("opt", "star", "plus")
_NON_IDENT = re.compile(r"[^A-Z0-9]+")


@dataclass(frozen=True)
class Unit:
    """One command (or its trees) owned by a model; ``trees`` are its parts/end Parts."""

    model: str
    trees: tuple[Part, ...]


@dataclass
class Deduped:
    """Rewritten trees (parallel to the input units) and the hoisted variables."""

    trees: list[list[Part]]
    variables: dict[str, Part]
    owners: dict[str, str | None] = field(default_factory=dict)


def canonical(part: Part) -> str:
    """Stable identity of a Part (key order independent)."""
    return json.dumps(part, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


def children(part: Part) -> list[Part]:
    """Direct child Parts."""
    kids: list[Part] = []
    for key in _LIST_KEYS:
        kids.extend(part.get(key, []))
    kids.extend(part[key] for key in _UNARY_KEYS if key in part)
    return kids


def weight(part: Part) -> int:
    """Total characters of pattern/literal text under ``part``."""
    own = len(part.get("regex", "")) + len(part.get("literal", ""))
    return own + sum(weight(c) for c in children(part))


def _descendants(part: Part) -> Iterator[Part]:
    for child in children(part):
        yield child
        yield from _descendants(child)


def name_hint(part: Part) -> str:
    """UPPER_SNAKE base name: first named leaf under ``part``, else ``COMMON``."""
    for node in [part, *_descendants(part)]:
        raw = node.get("name") or ""
        ident = _NON_IDENT.sub("_", raw.upper()).strip("_")
        if ident:
            return ident if ident[0].isalpha() else f"V_{ident}"
    return FALLBACK_NAME


def _unique(base: str, used: set[str]) -> str:
    name, n = base, 1
    while name in used:
        n += 1
        name = f"{base}_{n}"
    used.add(name)
    return name


def _replace(part: Part, key: str, ref: Part) -> Part:
    """Copy of ``part`` with every proper descendant whose identity is ``key`` replaced."""
    out = dict(part)
    for name in _LIST_KEYS:
        if name in out:
            out[name] = [_swap(c, key, ref) for c in out[name]]
    for name in _UNARY_KEYS:
        if name in out:
            out[name] = _swap(out[name], key, ref)
    return out


def _swap(part: Part, key: str, ref: Part) -> Part:
    return ref if canonical(part) == key else _replace(part, key, ref)


def _contains(trees: Sequence[Part], key: str) -> bool:
    return any(canonical(d) == key for t in trees for d in _descendants(t))


def _candidates(trees: Sequence[Part]) -> Iterator[Part]:
    for tree in trees:
        for node in _descendants(tree):
            if "ref" not in node and weight(node) >= MIN_WEIGHT:
                yield node


def _scan(units: list[tuple[str, list[Part]]]) -> tuple[dict[str, set[int]], dict[str, Part]]:
    index: dict[str, set[int]] = {}
    sample: dict[str, Part] = {}
    for uid, (_, trees) in enumerate(units):
        for node in _candidates(trees):
            key = canonical(node)
            index.setdefault(key, set()).add(uid)
            sample[key] = node
    return index, sample


def _refs(part: Part) -> Iterator[str]:
    if "ref" in part:
        yield part["ref"]
    for child in children(part):
        yield from _refs(child)


def _assign_owners(
    units: list[tuple[str, list[Part]]], variables: dict[str, Part], n_real: int
) -> dict[str, str | None]:
    models: dict[str, set[str]] = {name: set() for name in variables}
    for model, trees in units[:n_real]:
        for ref in {r for t in trees for r in _refs(t)}:
            models[ref].add(model)
    changed = True
    while changed:
        changed = False
        for name, definition in variables.items():
            for ref in set(_refs(definition)):
                if not models[name] <= models[ref]:
                    models[ref] |= models[name]
                    changed = True
    return {n: next(iter(m)) if len(m) == 1 else None for n, m in models.items()}


def dedupe(inputs: Sequence[Unit]) -> Deduped:
    """Hoist repeated subtrees of ``inputs`` into variables; see module docstring."""
    units = [(u.model, list(u.trees)) for u in inputs]
    n_real = len(units)
    index, sample = _scan(units)
    order = sorted(sample, key=lambda k: (-weight(sample[k]), k))
    variables: dict[str, Part] = {}
    used: set[str] = set()
    for key in order:
        hits = [u for u in sorted(index[key]) if _contains(units[u][1], key)]
        if len(hits) < MIN_COMMANDS:
            continue
        name = _unique(name_hint(sample[key]), used)
        ref: Part = {"ref": name}
        for uid in hits:
            model, trees = units[uid]
            units[uid] = (model, [_replace(t, key, ref) for t in trees])
        variables[name] = sample[key]
        units.append(("", [sample[key]]))
        for node in _candidates([sample[key]]):
            index.setdefault(canonical(node), set()).add(len(units) - 1)
    # Variable definitions themselves were rewritten as units; read them back.
    for offset, name in enumerate(variables):
        variables[name] = units[n_real + offset][1][0]
    owners = _assign_owners(units, variables, n_real)
    return Deduped([t for _, t in units[:n_real]], variables, owners)
