"""Command model: types shared by the loader and the resolver (contract I2).

Parts and entries stay plain ``dict`` structures so downstream code (interpreter and
emitters) can walk them recursively without a class hierarchy.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

Part = dict[str, Any]
Entry = dict[str, Any]


class ModelError(Exception):
    """A model problem located by file and JSON pointer."""

    def __init__(self, message: str, file: str | None = None, pointer: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.file = file
        self.pointer = pointer

    def __str__(self) -> str:
        where = f"{self.file or '<model>'}:{self.pointer or '/'}"
        return f"{where}: {self.message}"


class ModelLoadError(Exception):
    """Raised by ``load_dir`` with every error found, not just the first."""

    def __init__(self, errors: list[ModelError]) -> None:
        super().__init__("\n".join(str(e) for e in errors))
        self.errors = errors


@dataclass(frozen=True)
class Model:
    """One validated model file. Container fields are read-only by convention."""

    id: str
    layer: str
    path: Path | None = None
    diagram: str | None = None
    include: list[str] = field(default_factory=list)
    variables: dict[str, Part] = field(default_factory=dict)
    contexts: dict[str, list[Entry]] = field(default_factory=dict)
    factory: str | None = None
    start_map: dict[str, list[str]] = field(default_factory=dict)
    empty_needs_end: bool = False
    overrides: dict[str, Entry] = field(default_factory=dict)
    insert_before: dict[str, list[Entry]] = field(default_factory=dict)
    insert_after: dict[str, list[Entry]] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedModel:
    """A model with every ``include`` and ``ref`` inlined.

    ``variables`` and ``contexts`` hold the model's own definitions merged over those of
    the models it includes (transitively); own definitions win. No resolved Part or entry
    contains ``ref`` or ``include``. Shared sub-structures are read-only by convention.
    ``includes`` lists the transitive model-level includes in resolver scope order
    (depth-first, deduplicated); ``factory``, ``start_map`` and ``empty_needs_end`` are
    copied unchanged.
    """

    id: str
    layer: str
    path: Path | None
    diagram: str | None
    variables: dict[str, Part]
    contexts: dict[str, list[Entry]]
    factory: str | None = None
    start_map: dict[str, list[str]] = field(default_factory=dict)
    includes: tuple[str, ...] = ()
    empty_needs_end: bool = False


ResolvedModels = dict[str, ResolvedModel]
