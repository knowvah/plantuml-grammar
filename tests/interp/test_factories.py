"""NON_COMMAND_FACTORIES: plain-line factories do not glue ``{{ ... }}`` units."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from tools.config import require
from tools.interp.factories import NON_COMMAND_FACTORIES

ROOT = Path(__file__).resolve().parents[2]
PIN = "97a5992"
OPAQUE = "opaque-no-regex-field"
COMMAND_BASE = "PSystemCommandFactory"
EXTENDS = re.compile(r"class\s+(\w+)(?:<[^>]*>)?\s+extends\s+(\w+)")


def extracted_factories() -> dict[str, list[dict[str, str]]]:
    found = {}
    for path in sorted((ROOT / "extracted").glob("*Factory*.json")):
        found[path.stem] = json.loads(path.read_text(encoding="utf-8")).get("unreachable", [])
    return found


def test_every_opaque_extracted_factory_is_plain_line() -> None:
    opaque = {
        entry["class"].rsplit(".", 1)[-1]
        for unreachable in extracted_factories().values()
        for entry in unreachable
        if entry["reason"] == OPAQUE
    }
    assert len(opaque) == 24
    assert opaque <= NON_COMMAND_FACTORIES


def test_command_factories_are_not_listed() -> None:
    names = set(extracted_factories())
    for command_factory in ("ClassDiagramFactory", "PSystemEbnfFactory", "PSystemSaltFactory"):
        assert command_factory in names
        assert command_factory not in NON_COMMAND_FACTORIES
    assert len(NON_COMMAND_FACTORIES) == 28
    assert NON_COMMAND_FACTORIES <= names


def upstream_superclass(simple: str, files: list[str]) -> str | None:
    path = next(f for f in files if f.endswith(f"/{simple}.java"))
    shown = subprocess.run(  # noqa: S603 - fixed argv
        ["git", "-C", str(require("src")), "show", f"{PIN}:{path}"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    )
    found = [m.group(2) for m in EXTENDS.finditer(shown.stdout) if m.group(1) == simple]
    return found[0] if found else None


@pytest.mark.corpus
def test_listing_matches_the_upstream_superclass_chains() -> None:
    listing = subprocess.run(  # noqa: S603 - fixed argv
        ["git", "-C", str(require("src")), "ls-tree", "-r", "--name-only", PIN],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    ).stdout.splitlines()
    for name in extracted_factories():
        chain, current = [], upstream_superclass(name, listing)
        while current is not None:
            chain.append(current)
            current = upstream_superclass(current, listing)
        assert (COMMAND_BASE not in chain) == (name in NON_COMMAND_FACTORIES), name
