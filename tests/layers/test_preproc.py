"""L1 preprocessor layer (``model/preproc.yaml``): surface syntax of TIM directives.

Every fixture under ``tests/fixtures/preproc`` has a ``.json`` sibling with the jar's
per-block verdicts. The interpreter runs each file the way upstream does
(``split_blocks``, then ``accepts(..., raw=True)``): the preproc model filters the body
lines, the rest go to the diagram models.

Raw mode cannot evaluate conditions or expand macros, so a few fixtures are known to
disagree with the jar; ``SEMANTIC_GAPS`` lists them with the reason, and the unit test
pins the opposite verdict so a change in either direction is noticed.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest

from tools.config import PIN_SHA, require
from tools.interp import accepts
from tools.interp.source import split_blocks
from tools.model import Model, Part, ResolvedModel, ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve

REPO = Path(__file__).resolve().parents[2]
MODEL_DIR = REPO / "model"
FIXTURES = REPO / "tests" / "fixtures" / "preproc"
DIRECTIVES = FIXTURES / "directives"
BUILTINS_SNAPSHOT = FIXTURES / "builtins.json"
PUML = sorted(FIXTURES.rglob("*.puml"))
PREPROC_ID = "preproc"
PREPROC_LAYER = "preproc"
BUILTIN_VARIABLE = "BUILTIN_FUNCTION"
UPSTREAM_PREFIX = "net.sourceforge.plantuml."
JAVA_ROOT = "src/main/java/"
LANGUAGE_DESCRIPTOR = JAVA_ROOT + "net/sourceforge/plantuml/syntax/LanguageDescriptor.java"
TCONTEXT = JAVA_ROOT + "net/sourceforge/plantuml/tim/TContext.java"
BUILTIN_DIR = JAVA_ROOT + "net/sourceforge/plantuml/tim/builtin/"
PREPROC_ADD = re.compile(r'^\s*preproc\.add\("(![a-z_]+)"\);')
ADD_FUNCTION = re.compile(r"^\s*functionsSet\.addFunction\(new (\w+)\(")
SIGNATURE = re.compile(r'new TFunctionSignature\("(%\w+)"')
REGISTRY_START = "private void addStandardFunctions("
METHOD_END = "\n\t}\n"
ARROW = "a -> b"

# syntax/LanguageDescriptor.java:278-312 at 97a5992, without the leading "!".
KEYWORDS = (
    "assert define definelong dump_memory else end enddefinelong endfor endfunction "
    "endif endprocedure endsub endwhile exit final foreach function if ifdef ifndef "
    "import include includedef includesub local log option pragma procedure return "
    "startsub theme undef unquoted while"
).split()

SEMANTIC_GAPS = {
    "forms/if-branch-bad-line.puml": "the jar skips the false !else branch; raw mode "
    "cannot evaluate conditions, so the branch's lines reach the diagram",
    "forms/startsub-unclosed.puml": "a missing !endsub is an error "
    "(tim/iterator/CodeIteratorSub.java:83-99); !startsub pushes a context so the sub "
    "body reaches the diagram, which cannot also check for the closing line",
    "forms/call-dollar-procedure.puml": "a procedure call expands to its body at the "
    "call site; raw mode does not expand, so the call line reaches the diagram",
}

# Rules decided by TLineType alone (Pattern2 is case-insensitive, regex/Pattern2.java:114);
# every other directive is re-read by an Eater with case-sensitive checkAndEatChar
# (tim/Eater.java:252-279), and !exit by StartUtils.isExit (utils/StartUtils.java:131-150).
CASE_INSENSITIVE_RULES = {
    "CodeIteratorIfElse",
    "CodeIteratorIfEndif",
    "CodeIteratorWhileEnd",
    "CodeIteratorForeachEnd",
    "CodeIteratorSubEnd",
    "TContextEndFunction",
}


@pytest.fixture(scope="module")
def raw_models() -> dict[str, Model]:
    return load_dir(MODEL_DIR)


@pytest.fixture(scope="module")
def models() -> ResolvedModels:
    return resolve(load_dir(MODEL_DIR))


def rel(path: Path) -> str:
    return path.relative_to(FIXTURES).as_posix()


def expected(path: Path) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = json.loads(path.with_suffix(".json").read_text())["blocks"]
    return blocks


def uml(*lines: str) -> str:
    return "\n".join(["@startuml", *lines, "@enduml"])


def failure(verdict: dict[str, Any]) -> tuple[int, str] | None:
    first = verdict["first_failure"]
    return None if first is None else (first["line"], first["text"])


def git_show(path: str) -> str:
    src = require("src")
    cmd = ["git", "-C", str(src), "show", f"{PIN_SHA}:{path}"]
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def iter_commands(model: Model | ResolvedModel) -> Iterator[dict[str, Any]]:
    for entries in model.contexts.values():
        yield from (e for e in entries if "command" in e)


def iter_leaves(part: Part) -> Iterator[Part]:
    if "regex" in part or "literal" in part:
        yield part
    for key in ("seq", "alt"):
        for child in part.get(key, []):
            yield from iter_leaves(child)
    for key in ("opt", "star", "plus"):
        if key in part:
            yield from iter_leaves(part[key])


def rule_leaves(entry: dict[str, Any]) -> Iterator[Part]:
    yield from iter_leaves(entry["parts"])
    if "end" in entry:
        yield from iter_leaves(entry["end"])


# --- upstream extraction (pure; the corpus tests feed them git show output) ---------


def language_descriptor_keywords(source: str) -> list[str]:
    """``preproc.add("!x")`` arguments in file order, without the ``!``."""
    return [m.group(1)[1:] for line in source.splitlines() if (m := PREPROC_ADD.match(line))]


def registry_classes(tcontext: str) -> list[str]:
    """Classes registered by ``TContext.addStandardFunctions`` (commented lines skipped)."""
    start = tcontext.index(REGISTRY_START)
    body = tcontext[start : tcontext.index(METHOD_END, start)]
    return [m.group(1) for line in body.splitlines() if (m := ADD_FUNCTION.match(line))]


def builtin_registry(tcontext: str, read_class: Callable[[str], str]) -> list[dict[str, str]]:
    """``{"name", "class"}`` per registered builtin, in registration order."""
    result = []
    for cls in registry_classes(tcontext):
        match = SIGNATURE.search(read_class(cls))
        assert match is not None, f"no TFunctionSignature literal in {cls}"
        result.append({"name": match.group(1), "class": cls})
    return result


def model_builtin_names(model: Model) -> list[str]:
    return [leaf["literal"] for leaf in iter_leaves(model.variables[BUILTIN_VARIABLE])]


# --- the model ------------------------------------------------------------------------


def test_there_is_exactly_one_preproc_layer_model(raw_models: dict[str, Model]) -> None:
    # tools/interp/engine.py:_preproc_model takes the first layer-preproc model.
    preproc = [m for m in raw_models.values() if m.layer == PREPROC_LAYER]
    assert [(m.id, m.path.name) for m in preproc] == [(PREPROC_ID, "preproc.yaml")]


def test_every_rule_cites_its_upstream_class(raw_models: dict[str, Model]) -> None:
    for entry in iter_commands(raw_models[PREPROC_ID]):
        prov = entry["provenance"]
        simple = prov["class"].rsplit(".", 1)[-1]
        assert prov["class"].startswith(UPSTREAM_PREFIX), entry["command"]
        assert prov["file"] == JAVA_ROOT + prov["class"].replace(".", "/") + ".java"
        assert prov["line"] >= 1
        assert entry["command"].startswith(simple), entry["command"]


def test_case_sensitivity_follows_the_upstream_reader(models: ResolvedModels) -> None:
    rules = {e["command"]: e for e in iter_commands(models[PREPROC_ID])}
    assert CASE_INSENSITIVE_RULES <= set(rules)
    for name, entry in rules.items():
        keyword = next(rule_leaves(entry))
        assert keyword.get("ci", False) is (name in CASE_INSENSITIVE_RULES), name


def test_builtin_names_equal_the_registry_snapshot(raw_models: dict[str, Model]) -> None:
    snapshot = json.loads(BUILTINS_SNAPSHOT.read_text())
    names = [f["name"] for f in snapshot["functions"]]
    assert len(names) == 74
    builtins = raw_models[PREPROC_ID].variables[BUILTIN_VARIABLE]
    assert model_builtin_names(raw_models[PREPROC_ID]) == names
    assert {leaf["ci"] for leaf in iter_leaves(builtins)} == {False}


# --- raw-mode behaviour -----------------------------------------------------------------


def test_procedure_with_end_is_accepted_and_without_end_rejected(
    models: ResolvedModels,
) -> None:
    body = ["!procedure $p($a)", "$a -> b", "!endprocedure", ARROW]
    assert accepts(models, uml(*body), raw=True)["accepted"] is True
    missing = accepts(models, uml(*body[:2], ARROW), raw=True)
    assert failure(missing) == (2, "!procedure $p($a)")


def test_procedure_body_never_reaches_the_diagram(models: ResolvedModels) -> None:
    text = uml("!procedure $p()", "]]] not a command", "!if", "!endprocedure", ARROW)
    assert accepts(models, text, raw=True)["accepted"] is True


def test_block_directive_bodies_reach_the_diagram(models: ResolvedModels) -> None:
    for opener, closer in (
        ("!if 1", "!endif"),
        ("!while 0", "!endwhile"),
        ("!foreach $i in [1]", "!endfor"),
        ("!startsub S", "!endsub"),
    ):
        verdict = accepts(models, uml(opener, "]]] bad", closer), raw=True)
        assert failure(verdict) == (3, "]]] bad"), opener


def test_closers_outside_their_block_reach_the_diagram(models: ResolvedModels) -> None:
    for closer in ("!endif", "!else", "!elseif 1", "!endwhile", "!endfor", "!endsub"):
        assert failure(accepts(models, uml(closer, ARROW), raw=True)) == (2, closer)


def test_eater_keywords_are_case_sensitive_and_closers_are_not(
    models: ResolvedModels,
) -> None:
    upper = accepts(models, uml("!IF 1", ARROW, "!endif"), raw=True)
    assert failure(upper) == (2, "!IF 1")
    closers = uml("!if 1", ARROW, "!ELSE", "!ENDIF", "!END PROCEDURE")
    assert accepts(models, closers, raw=True)["accepted"] is True


def test_exit_drops_the_rest_of_the_block(models: ResolvedModels) -> None:
    verdict = accepts(models, uml(ARROW, "!exit", "]]] ignored", "!endif"), raw=True)
    assert (verdict["accepted"], verdict["diagram"]) == (True, "SEQUENCE")


def test_multiline_json_affectation_is_one_directive(models: ResolvedModels) -> None:
    text = uml("!$x = {", '"a": {', '"b": 1', "}", "}", ARROW)
    assert accepts(models, text, raw=True)["accepted"] is True


# --- fixtures -----------------------------------------------------------------------------


@pytest.mark.parametrize("path", PUML, ids=rel)
def test_interpreter_verdict_equals_expected(models: ResolvedModels, path: Path) -> None:
    got = [accepts(models, block, raw=True) for block in split_blocks(path.read_text())]
    want = expected(path)
    if rel(path) in SEMANTIC_GAPS:
        assert [g["accepted"] for g in got] == [not w["accepted"] for w in want]
        return
    assert [g["accepted"] for g in got] == [w["accepted"] for w in want]
    for verdict, block in zip(got, want, strict=True):
        if block["diagram"] is not None:
            assert verdict["diagram"] == block["diagram"]


@pytest.mark.parametrize("keyword", KEYWORDS)
def test_every_keyword_has_a_positive_and_a_negative_fixture(keyword: str) -> None:
    pos, neg = DIRECTIVES / f"{keyword}-pos.puml", DIRECTIVES / f"{keyword}-neg.puml"
    for path in (pos, neg):
        assert f"!{keyword}" in path.read_text().lower()
    assert [b["accepted"] for b in expected(pos)] == [True]
    assert [b["accepted"] for b in expected(neg)] == [False]


def test_semantic_gaps_name_existing_fixtures() -> None:
    assert set(SEMANTIC_GAPS) <= {rel(p) for p in PUML}


def test_language_descriptor_parser_reads_preproc_adds() -> None:
    source = '\t\tkeyword.add("x");\n\t\tpreproc.add("!assert");\n\t\tpreproc.add("!while");\n'
    assert language_descriptor_keywords(source) == ["assert", "while"]


def test_registry_parser_skips_commented_registrations() -> None:
    tcontext = (
        "\tprivate void addStandardFunctions(Defines defines) {\n"
        "\t\tfunctionsSet.addFunction(new Upper());\n"
        "\t\t// functionsSet.addFunction(new LoadJsonLegacy());\n"
        "\t\tif (!TeaVM.isTeaVM()) {\n\t\t\tfunctionsSet.addFunction(new GetStdlib());\n\t\t}\n"
        "\t}\n\tother();\n\t}\n"
    )
    classes = {
        "Upper": 'new TFunctionSignature("%upper", 1)',
        "GetStdlib": 'new TFunctionSignature("%get_stdlib", 1)',
    }
    assert builtin_registry(tcontext, classes.__getitem__) == [
        {"name": "%upper", "class": "Upper"},
        {"name": "%get_stdlib", "class": "GetStdlib"},
    ]


# --- corpus: the jar and the upstream source at the pin -----------------------------------


@pytest.mark.corpus
def test_expected_verdicts_equal_the_oracle() -> None:
    from tools.validate.oracle import oracle_verdicts

    verdicts = oracle_verdicts(PUML)
    for path in PUML:
        oracle = [
            {"accepted": b["accepted"], "diagram": b["diagram_type"] if b["accepted"] else None}
            for b in verdicts[str(path)]
        ]
        assert oracle == expected(path), rel(path)


@pytest.mark.corpus
def test_keywords_equal_the_language_descriptor() -> None:
    assert language_descriptor_keywords(git_show(LANGUAGE_DESCRIPTOR)) == KEYWORDS


@pytest.mark.corpus
def test_builtin_snapshot_equals_the_upstream_registry() -> None:
    def read_class(cls: str) -> str:
        return git_show(f"{BUILTIN_DIR}{cls}.java")

    snapshot = json.loads(BUILTINS_SNAPSHOT.read_text())
    assert builtin_registry(git_show(TCONTEXT), read_class) == snapshot["functions"]


@pytest.mark.corpus
def test_provenance_lines_resolve_at_the_pin(raw_models: dict[str, Model]) -> None:
    for entry in iter_commands(raw_models[PREPROC_ID]):
        prov = entry["provenance"]
        lines = git_show(prov["file"]).splitlines()
        simple = prov["class"].rsplit(".", 1)[-1]
        assert prov["line"] <= len(lines), entry["command"]
        assert lines[prov["line"] - 1].strip(), entry["command"]
        assert re.search(rf"\b(class|enum) {simple}\b", "\n".join(lines)), entry["command"]
