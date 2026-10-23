"""Tests for ``require_pop``, ``reject``, ``provenance.also`` and ``\\u`` escapes in regexes."""

from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path

import pytest

from tools.config import ENV_VARS, PIN_SHA
from tools.model import ModelLoadError
from tools.model.load import check_pattern, load_dir
from tools.model.resolve import resolve

HEADER = "schema_version: 1\nid: m\nlayer: diagram\ndiagram: CLASS\n"
ALSO_PATTERN_OK = "src/main/java/net/sourceforge/plantuml/Foo.java:42"
ALSO_RANGE_OK = "src/main/java/net/sourceforge/plantuml/Foo.java:42-50"


def entry(command: str = "C", **extra: str) -> str:
    body = f"    - command: {command}\n      provenance: {{class: X}}\n"
    body += "      kind: single\n      parts: {regex: x}\n"
    return body + "".join(f"      {k}: {v}\n" for k, v in extra.items())


def model(tmp_path: Path, contexts: str, extra: str = "") -> Path:
    text = HEADER + extra + "contexts:\n  main:\n" + contexts + "  body:\n" + entry("P", pop="true")
    (tmp_path / "m.yaml").write_text(text, encoding="utf-8")
    return tmp_path


def errors(tmp_path: Path) -> str:
    with pytest.raises(ModelLoadError) as info:
        load_dir(tmp_path)
    return str(info.value)


def test_require_pop_with_push_loads(tmp_path: Path) -> None:
    models = load_dir(model(tmp_path, entry(push="body", require_pop="true")))
    assert models["m"].contexts["main"][0]["require_pop"] is True


def test_require_pop_without_push_is_rejected(tmp_path: Path) -> None:
    assert "require_pop" in errors(model(tmp_path, entry(require_pop="true")))


def test_require_pop_must_be_true(tmp_path: Path) -> None:
    assert "True was expected" in errors(model(tmp_path, entry(push="body", require_pop="false")))


def test_reject_single_loads(tmp_path: Path) -> None:
    models = load_dir(model(tmp_path, entry(reject="true")))
    assert models["m"].contexts["main"][0]["reject"] is True


@pytest.mark.parametrize("other", ["push: body", "set: body", "pop: true"])
def test_reject_forbids_transitions(tmp_path: Path, other: str) -> None:
    key, value = other.split(": ")
    assert errors(model(tmp_path, entry(reject="true", **{key: value})))


def test_reject_requires_single_kind(tmp_path: Path) -> None:
    text = entry(reject="true").replace("kind: single", "kind: opaque")
    assert errors(model(tmp_path, text))


def test_reject_allowed_in_inserts_and_overrides(tmp_path: Path) -> None:
    extra = (
        "insert_before:\n  C:\n"
        + textwrap.indent(entry("R", reject="true"), "  ")
        + "overrides:\n  D: {reject: true}\n"
    )
    contexts = entry("C") + entry("D")
    resolved = resolve(load_dir(model(tmp_path, contexts, extra)))["m"]
    main = resolved.contexts["main"]
    assert [(e["command"], e.get("reject")) for e in main] == [
        ("R", True),
        ("C", None),
        ("D", True),
    ]
    assert main[2]["refined_by"] == "m"


def test_require_pop_override_needs_push_in_merged_entry(tmp_path: Path) -> None:
    extra = "overrides:\n  C: {require_pop: true}\n"
    assert "invalid entry for 'C'" in errors(model(tmp_path, entry("C"), extra))
    extra = "overrides:\n  C: {push: body, require_pop: true}\n"
    merged = resolve(load_dir(model(tmp_path, entry("C"), extra)))["m"].contexts["main"][0]
    assert (merged["push"], merged["require_pop"]) == ("body", True)


def test_require_pop_override_can_be_deleted_with_null(tmp_path: Path) -> None:
    extra = "overrides:\n  C: {require_pop: null}\n"
    contexts = entry("C", push="body", require_pop="true")
    merged = resolve(load_dir(model(tmp_path, contexts, extra)))["m"].contexts["main"][0]
    assert "require_pop" not in merged


# --- provenance.also ----------------------------------------------------------------------


def prov_model(tmp_path: Path, also: str) -> Path:
    text = HEADER + "contexts:\n  main:\n    - command: C\n      kind: single\n"
    text += f"      provenance: {{class: X, also: {also}}}\n      parts: {{regex: x}}\n"
    (tmp_path / "m.yaml").write_text(text, encoding="utf-8")
    return tmp_path


def test_provenance_also_accepts_citations(tmp_path: Path) -> None:
    models = load_dir(prov_model(tmp_path, f"[{ALSO_PATTERN_OK}, {ALSO_RANGE_OK}]"))
    also = models["m"].contexts["main"][0]["provenance"]["also"]
    assert also == [ALSO_PATTERN_OK, ALSO_RANGE_OK]


@pytest.mark.parametrize(
    "bad", ["[Foo.java:1]", "[src/main/java/a/Foo.java]", "[src/main/java/Foo.java:x]", "foo"]
)
def test_provenance_also_rejects_malformed(tmp_path: Path, bad: str) -> None:
    assert errors(prov_model(tmp_path, bad))


# --- \u escapes ---------------------------------------------------------------------------


@pytest.mark.parametrize("pattern", ["a\\uE100b", "\\u00e9", "x\\\\\\u0041"])
def test_unicode_escape_is_rejected_with_hint(pattern: str) -> None:
    problem = check_pattern(pattern)
    assert problem is not None
    assert "\\u escape" in problem
    assert "literal character" in problem


@pytest.mark.parametrize("pattern", ["a\\\\u0041", "é", "a\ue100b", "\\p{L}", "\\\\\\\\u"])
def test_literal_characters_and_escaped_backslashes_are_fine(pattern: str) -> None:
    assert check_pattern(pattern) is None


def test_unicode_escape_in_model_is_a_load_error(tmp_path: Path) -> None:
    text = HEADER + "contexts:\n  main:\n    - command: C\n      provenance: {class: X}\n"
    text += "      kind: single\n      parts: {regex: 'a\\uE100'}\n"
    (tmp_path / "m.yaml").write_text(text, encoding="utf-8")
    assert "\\u escape" in errors(tmp_path)


# --- corpus: every `also` citation resolves at the pin ------------------------------------

MODEL_DIR = Path(__file__).resolve().parents[2] / "model"


def collect_also(models: dict[str, object]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []

    def walk(entries: list[dict[str, object]], owner: str) -> None:
        for e in entries:
            prov = e.get("provenance") if isinstance(e, dict) else None
            if isinstance(prov, dict):
                found.extend((owner, c) for c in prov.get("also", []))

    for mid, m in models.items():
        for entries in m.contexts.values():  # type: ignore[attr-defined]
            walk(entries, mid)
        for patch in m.overrides.values():  # type: ignore[attr-defined]
            walk([patch], mid)
        for group in (m.insert_before, m.insert_after):  # type: ignore[attr-defined]
            for entries in group.values():
                walk(entries, mid)
    return found


def test_collect_also_walks_contexts_overrides_and_inserts(tmp_path: Path) -> None:
    extra = (
        "overrides:\n  C: {provenance: {class: X, also: [" + ALSO_PATTERN_OK + "]}}\n"
        "insert_after:\n  C:\n    - command: N\n      kind: single\n      parts: {regex: y}\n"
        "      provenance: {class: Y, also: [" + ALSO_RANGE_OK + "]}\n"
    )
    models = load_dir(model(tmp_path, entry("C"), extra))
    assert sorted(c for _, c in collect_also(models)) == [ALSO_PATTERN_OK, ALSO_RANGE_OK]


@pytest.mark.corpus
def test_also_citations_resolve_at_pin() -> None:
    import os

    src = Path(os.environ.get(ENV_VARS["src"], Path.home() / "git/plantuml"))
    for owner, cite in collect_also(load_dir(MODEL_DIR)):
        path, _, lines = cite.rpartition(":")
        last = int(lines.split("-")[-1])
        shown = subprocess.run(  # noqa: S603
            ["git", "-C", str(src), "show", f"{PIN_SHA}:{path}"],  # noqa: S607
            capture_output=True,
            text=True,
            check=False,
        )
        assert shown.returncode == 0, f"{owner}: {cite} missing at {PIN_SHA[:7]}"
        assert len(shown.stdout.splitlines()) >= last, f"{owner}: {cite} beyond end of file"


def test_empty_needs_end_loads_and_resolves(tmp_path: Path) -> None:
    models = load_dir(model(tmp_path, entry(), "empty_needs_end: true\n"))
    assert models["m"].empty_needs_end is True
    assert resolve(models)["m"].empty_needs_end is True


def test_empty_needs_end_defaults_to_false(tmp_path: Path) -> None:
    models = load_dir(model(tmp_path, entry()))
    assert models["m"].empty_needs_end is False
    assert resolve(models)["m"].empty_needs_end is False


def test_empty_needs_end_is_diagram_layer_only(tmp_path: Path) -> None:
    text = "schema_version: 1\nid: s\nlayer: shared\nempty_needs_end: true\n"
    (tmp_path / "s.yaml").write_text(text, encoding="utf-8")
    assert "empty_needs_end" in errors(tmp_path)


def test_empty_needs_end_must_be_boolean(tmp_path: Path) -> None:
    assert "boolean" in errors(model(tmp_path, entry(), "empty_needs_end: maybe\n"))


def test_shadows_is_not_a_model_key(tmp_path: Path) -> None:
    assert errors(model(tmp_path, entry(reject="true", shadows="[C]")))
