"""Tests for tools.model.load."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from tools.model import ModelLoadError
from tools.model.load import check_pattern, iter_regexes, load_dir, main

FIXTURES = Path(__file__).parent / "fixtures" / "valid"
HEADER = "schema_version: 1\nid: m\nlayer: shared\n"


def write(tmp_path: Path, body: str, name: str = "m.yaml") -> Path:
    (tmp_path / name).write_text(textwrap.dedent(body), encoding="utf-8")
    return tmp_path


def load_errors(tmp_path: Path) -> list[str]:
    with pytest.raises(ModelLoadError) as info:
        load_dir(tmp_path)
    return [str(e) for e in info.value.errors]


def cmd(parts: str) -> str:
    return (
        HEADER
        + "contexts:\n  main:\n    - command: C\n      provenance: {class: X}\n"
        + f"      kind: single\n      parts: {parts}\n"
    )


def test_load_valid_dir_recursively_with_stem_ids() -> None:
    models = load_dir(FIXTURES)
    assert sorted(models) == ["a", "b", "c", "gen"]
    assert models["a"].diagram == "CLASS"
    assert models["a"].include == ["b"]
    assert models["gen"].path == FIXTURES / "generated" / "gen.yaml"
    assert models["c"].variables["COLOR"] == {"regex": "#\\w+"}


def test_empty_and_schema_only_dir_load_nothing(tmp_path: Path) -> None:
    (tmp_path / "schema.json").write_text("{}", encoding="utf-8")
    assert load_dir(tmp_path) == {}


def test_unknown_key_names_file_and_pointer(tmp_path: Path) -> None:
    write(tmp_path, HEADER + "bogus: 1\n")
    assert load_errors(tmp_path) == [f"{tmp_path / 'm.yaml'}:/bogus: unknown key"]


def test_unknown_key_deep_inside_part(tmp_path: Path) -> None:
    write(tmp_path, cmd("{regex: a, wat: 1}"))
    errors = load_errors(tmp_path)
    assert errors == [f"{tmp_path / 'm.yaml'}:/contexts/main/0/parts/wat: unknown key"]


def test_unknown_key_in_entry(tmp_path: Path) -> None:
    write(tmp_path, cmd("{regex: a}") + "      extra: 1\n")
    assert load_errors(tmp_path)[0].endswith(":/contexts/main/0/extra: unknown key")


def test_macro_rejected(tmp_path: Path) -> None:
    write(tmp_path, cmd("{regex: '[%pLN]'}"))
    errors = load_errors(tmp_path)
    assert errors == [
        f"{tmp_path / 'm.yaml'}:/contexts/main/0/parts/regex: unexpanded upstream macro '%pLN'"
    ]


@pytest.mark.parametrize("macro", ["%s", "%q", "%g", "%pLN"])
def test_each_upstream_macro_rejected(macro: str) -> None:
    assert check_pattern(f"a{macro}b") == f"unexpanded upstream macro '{macro}'"


@pytest.mark.parametrize("pattern", ["\\d+%", "100%", "\\p{L}\\p{N}", "(?<n>x)", "%x"])
def test_valid_patterns_accepted(pattern: str) -> None:
    assert check_pattern(pattern) is None


def test_uncompilable_regex_rejected(tmp_path: Path) -> None:
    write(tmp_path, cmd("{regex: '('}"))
    assert "regex does not compile" in load_errors(tmp_path)[0]


def test_regex_in_variable_and_end_checked(tmp_path: Path) -> None:
    body = HEADER + "variables:\n  V: {regex: '['}\n"
    write(tmp_path, body)
    assert load_errors(tmp_path)[0].split(": ")[0].endswith(":/variables/V/regex")
    multi = cmd("{regex: a}").replace("single", "multiline")
    write(tmp_path, multi + "      end: {regex: '('}\n")
    assert load_errors(tmp_path)[0].split(": ")[0].endswith(":/contexts/main/0/end/regex")


def test_iter_regexes_walks_nested_parts() -> None:
    part = {
        "seq": [{"opt": {"regex": "a"}}, {"alt": [{"regex": "b"}, {"literal": "c", "ci": True}]}]
    }
    assert list(iter_regexes(part, "/p")) == [
        ("/p/seq/0/opt/regex", "a"),
        ("/p/seq/1/alt/0/regex", "b"),
    ]


def test_id_must_match_stem(tmp_path: Path) -> None:
    write(tmp_path, HEADER, name="other.yaml")
    assert load_errors(tmp_path) == [
        f"{tmp_path / 'other.yaml'}:/id: id 'm' must equal file stem 'other'"
    ]


def test_duplicate_id_across_subdirs(tmp_path: Path) -> None:
    write(tmp_path, HEADER)
    (tmp_path / "sub").mkdir()
    write(tmp_path / "sub", HEADER)
    errors = load_errors(tmp_path)
    assert len(errors) == 1
    assert "duplicate id 'm'" in errors[0]


def test_unknown_ref_target_reported(tmp_path: Path) -> None:
    write(tmp_path, cmd("{ref: NOPE}"))
    assert load_errors(tmp_path)[0].endswith(":/contexts/main/0/parts/ref: unknown variable 'NOPE'")


def test_unknown_include_model_reported(tmp_path: Path) -> None:
    write(tmp_path, HEADER + "include: [ghost]\n")
    assert load_errors(tmp_path)[0].endswith(":/include/0: unknown model id 'ghost'")


def test_invalid_yaml_and_non_mapping(tmp_path: Path) -> None:
    write(tmp_path, "a: [unclosed\n")
    assert "invalid YAML" in load_errors(tmp_path)[0]
    write(tmp_path, "- 1\n")
    assert load_errors(tmp_path)[0].endswith(":/: [1] is not of type 'object'")


def test_layer_diagram_rules(tmp_path: Path) -> None:
    write(tmp_path, "schema_version: 1\nid: m\nlayer: diagram\n")
    assert len(load_errors(tmp_path)) == 1
    write(tmp_path, HEADER + "diagram: CLASS\n")
    assert len(load_errors(tmp_path)) == 1


def test_transition_exclusive_and_end_rules(tmp_path: Path) -> None:
    write(tmp_path, cmd("{regex: a}") + "      push: x\n      pop: true\n")
    assert len(load_errors(tmp_path)) == 1
    write(tmp_path, cmd("{regex: a}") + "      end: {regex: b}\n")
    assert len(load_errors(tmp_path)) == 1


def test_part_requires_exactly_one_form(tmp_path: Path) -> None:
    write(tmp_path, cmd("{regex: a, literal: b, ci: true}"))
    assert len(load_errors(tmp_path)) >= 1
    write(tmp_path, cmd("{literal: b}"))
    assert len(load_errors(tmp_path)) >= 1


def test_not_a_directory(tmp_path: Path) -> None:
    assert load_errors(tmp_path / "missing") == [f"{tmp_path / 'missing'}:/: not a directory"]


def test_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--check", str(FIXTURES)]) == 0
    assert capsys.readouterr().out == "ok: 4 model(s)\n"
    write(tmp_path, HEADER + "bogus: 1\n")
    assert main(["--check", str(tmp_path)]) == 1
    assert ":/bogus: unknown key" in capsys.readouterr().err


def test_factory_and_start_map_keys_are_layer_scoped(tmp_path: Path) -> None:
    (tmp_path / "doc.yaml").write_text(
        "schema_version: 1\nid: doc\nlayer: document\nstart_map: {uml: [ClassDiagramFactory]}\n"
    )
    (tmp_path / "d.yaml").write_text(
        "schema_version: 1\nid: d\nlayer: diagram\ndiagram: CLASS\nfactory: ClassDiagramFactory\n"
    )
    assert sorted(load_dir(tmp_path)) == ["d", "doc"]
    (tmp_path / "s.yaml").write_text(
        "schema_version: 1\nid: s\nlayer: shared\nfactory: X\nstart_map: {uml: [X]}\n"
    )
    with pytest.raises(ModelLoadError) as exc:
        load_dir(tmp_path)
    assert {e.file.endswith("s.yaml") for e in exc.value.errors} == {True}


def test_factory_and_start_map_are_carried_on_the_model(tmp_path: Path) -> None:
    (tmp_path / "doc.yaml").write_text(
        "schema_version: 1\nid: doc\nlayer: document\n"
        "start_map: {uml: [SequenceDiagramFactory, ClassDiagramFactory]}\n"
    )
    (tmp_path / "d.yaml").write_text(
        "schema_version: 1\nid: d\nlayer: diagram\ndiagram: CLASS\nfactory: ClassDiagramFactory\n"
    )
    models = load_dir(tmp_path)
    assert models["doc"].start_map == {"uml": ["SequenceDiagramFactory", "ClassDiagramFactory"]}
    assert models["doc"].factory is None
    assert models["d"].factory == "ClassDiagramFactory"
    assert models["d"].start_map == {}


def test_cli_check_fails_on_two_top_models_for_one_factory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for mid in ("x1", "x2"):
        (tmp_path / f"{mid}.yaml").write_text(
            f"schema_version: 1\nid: {mid}\nlayer: diagram\ndiagram: CLASS\nfactory: XFactory\n"
        )
    assert main(["--check", str(tmp_path)]) == 1
    err = capsys.readouterr().err
    assert "two top models for factory 'XFactory'" in err
    assert "'x1'" in err and "'x2'" in err
