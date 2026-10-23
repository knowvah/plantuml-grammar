"""Schema and patch tests for ``gives``, ``needs`` and ``trim: false``."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from tools.model import ModelLoadError
from tools.model.load import load_dir
from tools.model.resolve import resolve

HEADER = "schema_version: 1\nid: m\nlayer: diagram\ndiagram: CLASS\n"


def entry(command: str = "C", kind: str = "single", **extra: str) -> str:
    body = f"    - command: {command}\n      provenance: {{class: X}}\n"
    body += f"      kind: {kind}\n      parts: {{regex: x}}\n"
    return body + "".join(f"      {k}: {v}\n" for k, v in extra.items())


def model(tmp_path: Path, contexts: str, extra: str = "") -> Path:
    (tmp_path / "m.yaml").write_text(
        HEADER + extra + "contexts:\n  main:\n" + contexts, encoding="utf-8"
    )
    return tmp_path


def errors(path: Path) -> str:
    with pytest.raises(ModelLoadError) as info:
        load_dir(path)
    return str(info.value)


def main_of(path: Path) -> list[dict[str, object]]:
    return resolve(load_dir(path))["m"].contexts["main"]


def test_gives_and_needs_load(tmp_path: Path) -> None:
    loaded = main_of(model(tmp_path, entry(gives="real_task") + entry("D", needs="real_task")))
    assert [(e.get("gives"), e.get("needs")) for e in loaded] == [
        ("real_task", None),
        (None, "real_task"),
    ]


@pytest.mark.parametrize("bad", ["Real", "1a", "a-b", "''"])
def test_flag_names_must_be_snake_case(tmp_path: Path, bad: str) -> None:
    assert errors(model(tmp_path, entry(gives=bad)))
    assert errors(model(tmp_path, entry(needs=bad)))


def test_trim_false_loads_for_single(tmp_path: Path) -> None:
    assert main_of(model(tmp_path, entry(trim="false")))[0]["trim"] is False


def test_trim_true_is_rejected(tmp_path: Path) -> None:
    assert errors(model(tmp_path, entry(trim="true")))


@pytest.mark.parametrize("kind", ["opaque", "multiline-bracket"])
def test_trim_requires_single_kind(tmp_path: Path, kind: str) -> None:
    assert errors(model(tmp_path, entry(kind=kind, trim="false")))


def test_trim_rejected_on_multiline(tmp_path: Path) -> None:
    text = entry(kind="multiline", trim="false").replace(
        "trim: false", "end: {regex: e}\n      trim: false"
    )
    assert errors(model(tmp_path, text))


def test_flags_and_trim_in_overrides_and_inserts(tmp_path: Path) -> None:
    extra = (
        "overrides:\n  C: {gives: g, trim: false}\n  D: {needs: g}\n"
        "insert_after:\n  C:\n" + textwrap.indent(entry("N", needs="g", trim="false"), "  ")
    )
    loaded = main_of(model(tmp_path, entry("C") + entry("D"), extra))
    assert [(e["command"], e.get("gives"), e.get("needs"), e.get("trim")) for e in loaded] == [
        ("C", "g", None, False),
        ("N", None, "g", False),
        ("D", None, "g", None),
    ]


def test_null_deletes_flags_and_trim(tmp_path: Path) -> None:
    extra = "overrides:\n  C: {gives: null, needs: null, trim: null}\n"
    contexts = entry("C", gives="g", needs="h", trim="false")
    loaded = main_of(model(tmp_path, contexts, extra))[0]
    assert {"gives", "needs", "trim"}.isdisjoint(loaded)


def test_override_trim_on_non_single_entry_is_invalid(tmp_path: Path) -> None:
    extra = "overrides:\n  C: {trim: false}\n"
    contexts = entry("C", kind="opaque")
    assert "invalid entry for 'C'" in errors(model(tmp_path, contexts, extra))


def test_emit_false_loads_and_true_is_rejected(tmp_path: Path) -> None:
    assert main_of(model(tmp_path, entry(emit="false")))[0]["emit"] is False
    assert errors(model(tmp_path, entry(emit="true")))


def test_emit_false_in_override_and_null_delete(tmp_path: Path) -> None:
    extra = "overrides:\n  C: {emit: false}\n  D: {emit: null}\n"
    loaded = main_of(model(tmp_path, entry("C") + entry("D", emit="false"), extra))
    assert [e.get("emit") for e in loaded] == [False, None]
