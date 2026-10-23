"""Pure resolution of ``include`` and ``ref`` in loaded models (no I/O).

Rules (see docs/grammar-guide.md, "Include and ref semantics"):

* Model-level ``include: [ids]`` makes the included models' variables and contexts
  visible; lookups try the model itself first, then its includes depth-first in order.
* ``{include: NAME}`` in a context splices entries in place. NAME is tried as a context
  visible from the model, then as a model id (that model's ``main``), and
  ``MODEL#CONTEXT`` names a context of a specific model.
* ``{ref: VAR}`` is replaced by the variable's resolved Part, looked up lexically from the
  model that contains the ``ref``.
"""

from __future__ import annotations

from typing import cast

from tools.model import (
    Entry,
    Model,
    ModelError,
    Part,
    ResolvedModel,
    ResolvedModels,
)
from tools.model.patch import apply_patches

ARROW = " → "
MAIN_CONTEXT = "main"
MODEL_CONTEXT_SEP = "#"
LIST_KEYS = ("seq", "alt")
UNARY_KEYS = ("opt", "star", "plus")
TRANSITION_KEYS = ("push", "set")
PART_KEYS = ("parts", "end")


def resolve(models: dict[str, Model]) -> ResolvedModels:
    """Inline every ``include`` and ``ref``; raise ``ModelError`` on the first problem."""
    _check_model_includes(models)
    resolver = _Resolver(models)
    resolved = {mid: resolver.resolve_model(mid) for mid in models}
    top_models(resolved)
    return resolved


def top_models(resolved: ResolvedModels) -> dict[str, str]:
    """``factory -> id`` of the top model per factory (docs/grammar-guide.md, dispatch).

    The top model is the one no other model declaring the same ``factory`` includes,
    transitively. Two tops for one factory raise ``ModelError`` naming both ids.
    """
    by_factory: dict[str, list[ResolvedModel]] = {}
    for m in resolved.values():
        if m.factory is not None:
            by_factory.setdefault(m.factory, []).append(m)
    tops: dict[str, str] = {}
    for factory, group in by_factory.items():
        included = {i for m in group for i in m.includes}
        for m in group:
            if m.id in included:
                continue
            if factory in tops:
                message = f"two top models for factory '{factory}': '{tops[factory]}' and '{m.id}'"
                raise ModelError(message, str(m.path) if m.path else m.id, "/factory")
            tops[factory] = m.id
    return tops


def _error(model: Model, pointer: str, message: str) -> ModelError:
    return ModelError(message, str(model.path) if model.path else model.id, pointer)


def _check_model_includes(models: dict[str, Model]) -> None:
    done: set[str] = set()
    for mid in models:
        _visit_includes(models, mid, [mid], done)


def _visit_includes(models: dict[str, Model], mid: str, path: list[str], done: set[str]) -> None:
    if mid in done:
        return
    for index, target in enumerate(models[mid].include):
        if target not in models:
            raise _error(models[mid], f"/include/{index}", f"unknown model id '{target}'")
        if target in path:
            cycle = ARROW.join([*path[path.index(target) :], target])
            raise _error(models[mid], f"/include/{index}", f"include cycle: {cycle}")
        _visit_includes(models, target, [*path, target], done)
    done.add(mid)


class _Resolver:
    def __init__(self, models: dict[str, Model]) -> None:
        self._models = models
        self._scopes: dict[str, list[str]] = {}
        self._vars: dict[tuple[str, str], Part] = {}

    def scope(self, mid: str) -> list[str]:
        """The model followed by its transitive includes, depth-first, deduplicated."""
        if mid not in self._scopes:
            order = [mid]
            for target in self._models[mid].include:
                order.extend(m for m in self.scope(target) if m not in order)
            self._scopes[mid] = order
        return self._scopes[mid]

    def find_var(self, mid: str, name: str) -> str | None:
        return next((m for m in self.scope(mid) if name in self._models[m].variables), None)

    def find_ctx(self, mid: str, name: str) -> str | None:
        return next((m for m in self.scope(mid) if name in self._models[m].contexts), None)

    def resolve_model(self, mid: str) -> ResolvedModel:
        model = self._models[mid]
        scope = self.scope(mid)
        var_names = dict.fromkeys(n for m in scope for n in self._models[m].variables)
        ctx_names = dict.fromkeys(n for m in scope for n in self._models[m].contexts)
        variables = {
            n: self._variable(self._owner(self.find_var(mid, n)), n, ()) for n in var_names
        }
        contexts = {n: self.expand_context(mid, n, ()) for n in ctx_names}
        contexts = apply_patches(self, self._models, mid, contexts)
        return ResolvedModel(
            mid,
            model.layer,
            model.path,
            model.diagram,
            variables,
            contexts,
            factory=model.factory,
            start_map=model.start_map,
            includes=tuple(scope[1:]),
            empty_needs_end=model.empty_needs_end,
        )

    @staticmethod
    def _owner(owner: str | None) -> str:
        # Callers pass names taken from a scope listing, so a definition always exists.
        return cast(str, owner)

    def _variable(self, owner: str, name: str, stack: tuple[str, ...]) -> Part:
        node = f"{owner}.{name}"
        if node in stack:
            cycle = ARROW.join([*stack[stack.index(node) :], node])
            raise _error(self._models[owner], f"/variables/{name}", f"variable cycle: {cycle}")
        if (owner, name) not in self._vars:
            raw = self._models[owner].variables[name]
            self._vars[(owner, name)] = self.expand_part(
                raw, owner, f"/variables/{name}", (*stack, node)
            )
        return self._vars[(owner, name)]

    def expand_part(self, part: Part, mid: str, pointer: str, stack: tuple[str, ...]) -> Part:
        if "ref" in part:
            name = part["ref"]
            owner = self.find_var(mid, name)
            if owner is None:
                raise _error(self._models[mid], f"{pointer}/ref", f"unknown variable '{name}'")
            return self._variable(owner, name, stack)
        for key in LIST_KEYS:
            if key in part:
                return {
                    key: [
                        self.expand_part(c, mid, f"{pointer}/{key}/{i}", stack)
                        for i, c in enumerate(part[key])
                    ]
                }
        for key in UNARY_KEYS:
            if key in part:
                return {key: self.expand_part(part[key], mid, f"{pointer}/{key}", stack)}
        return dict(part)

    def expand_context(self, mid: str, name: str, stack: tuple[str, ...]) -> list[Entry]:
        owner = self._owner(self.find_ctx(mid, name))
        node = f"{owner}.{name}"
        if node in stack:
            cycle = ARROW.join([*stack[stack.index(node) :], node])
            raise _error(self._models[owner], f"/contexts/{name}", f"include cycle: {cycle}")
        out: list[Entry] = []
        for index, entry in enumerate(self._models[owner].contexts[name]):
            pointer = f"/contexts/{name}/{index}"
            if "include" in entry:
                target_model, target_ctx = self.include_target(owner, entry["include"], pointer)
                out.extend(self.expand_context(target_model, target_ctx, (*stack, node)))
            else:
                out.append(self.expand_entry(owner, entry, pointer))
        return out

    def include_target(self, mid: str, name: str, pointer: str) -> tuple[str, str]:
        if MODEL_CONTEXT_SEP in name:
            target, ctx = name.split(MODEL_CONTEXT_SEP, 1)
        elif self.find_ctx(mid, name):
            return mid, name
        else:
            target, ctx = name, MAIN_CONTEXT
        if target not in self._models or not self.find_ctx(target, ctx):
            raise _error(
                self._models[mid], f"{pointer}/include", f"include target '{name}' not found"
            )
        return target, ctx

    def expand_entry_parts(self, mid: str, entry: Entry, pointer: str) -> Entry:
        """Copy of ``entry`` with its ``parts``/``end`` (when Parts) ref-expanded in ``mid``."""
        out = dict(entry)
        for key in PART_KEYS:
            if isinstance(entry.get(key), dict):
                out[key] = self.expand_part(entry[key], mid, f"{pointer}/{key}", ())
        return out

    def missing_transition(self, mid: str, entry: Entry) -> str | None:
        """The ``push``/``set`` key of ``entry`` naming a context invisible from ``mid``."""
        return next(
            (k for k in TRANSITION_KEYS if entry.get(k) and not self.find_ctx(mid, entry[k])),
            None,
        )

    def expand_entry(self, mid: str, entry: Entry, pointer: str) -> Entry:
        out = self.expand_entry_parts(mid, entry, pointer)
        key = self.missing_transition(mid, entry)
        if key:
            raise _error(self._models[mid], f"{pointer}/{key}", f"unknown context '{entry[key]}'")
        return out
