"""Toy model sets and the blocks their Python tests use, for the conformance goldens (C5).

Each ``ToySpec`` mirrors one set of the interpreter unit tests under ``tests/interp``. The
model ids and factories follow the TS engine's hand-made toys
(``packages/engine/test/fixtures/engine-*.engine.json``) so the two can be compared by name.
A case is a block plus the optional start map that picks the model under test.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from tests.interp import test_document_dispatch as dispatch_toys
from tests.interp import test_flags_trim as flags_toys
from tests.interp import test_plain_lines_empty_end as plain_toys
from tests.interp import test_require_pop_reject as pop_toys
from tests.interp.conftest import FIXTURES as INTERP_FIXTURES
from tools.model import ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve

StartMap = dict[str, list[str]]
Build = Callable[[Path], ResolvedModels]
START = "uml"


@dataclass(frozen=True)
class Case:
    """One block and the start map under which it is judged (``None``: default dispatch)."""

    text: str
    start_map: StartMap | None = None


@dataclass(frozen=True)
class ToySpec:
    """A named toy model set: how to build it in a scratch dir and the cases to record."""

    name: str
    build: Build
    cases: Sequence[Case]


def uml(*lines: str) -> str:
    return "\n".join(["@startuml", *lines, "@enduml"])


def on(model_id: str, *lines: str) -> Case:
    """A ``@startuml`` block judged by model ``model_id`` only."""
    return Case(uml(*lines), {START: [model_id]})


def raw_text(model_id: str, text: str) -> Case:
    return Case(text, {START: [model_id]})


def from_yaml(files: dict[str, str]) -> Build:
    def build(tmp: Path) -> ResolvedModels:
        for name, text in files.items():
            (tmp / f"{name}.yaml").write_text(text, encoding="utf-8")
        return resolve(load_dir(tmp))

    return build


def header(model_id: str, extra: str = "") -> str:
    return f"schema_version: 1\nid: {model_id}\nlayer: diagram\ndiagram: CLASS\n{extra}"


# --- toys: tests/interp/fixtures, driven by test_engine.py ----------------------------------

TOYS_BLOCKS = [
    uml("alpha x"),
    uml("beta x", "beta y"),
    uml("title hello"),
    uml("note", "anything goes", "alpha ignored by class", "end note", "beta z"),
    uml("note", "body", "end note", "nonsense here"),
    uml("note", "beta x"),
    uml("note", "{{", "end note", "}}", "end note", "beta q"),
    uml("note", "{{", "end note", "end note", "beta q"),
    "\n@startuml\nalpha ok\n  bogus line  \n@enduml",
    uml("dup", "one"),
    uml("dup", "two"),
    uml("open {", "member a", "member b", "}", "beta c"),
    uml("member a"),
    uml("open {", "beta c"),
    uml("swap", "two"),
    uml("swap", "one"),
    uml("swap", "two", "beta x"),
    uml("}"),
    uml("package a {", "inner {", "}", "}", "beta x"),
    uml("package a {", "inner {", "}", "beta x"),
    uml("package a {", "}", "}"),
    "@startdot\ndigraph g {\n}\n@enddot",
    "@startdot\nnot digraph\n@enddot",
    "\n@startuml\n' only a comment\n\n@enduml",
    "beta x",
    "alpha x\nzzz",
    "@startnope\nalpha x\n@endnope",
    "@startuml\r\n\talpha x  \r\n@enduml\r\n",
    uml("title a "),
    uml("title a\x85"),
    uml("title a b"),
    uml("title a  "),
    uml("title –"),
    uml("opt", "beta x"),
    uml("opt", "z"),
    uml("wrap a", "b", "beta x"),
    uml("wrap a", "b", "c"),
    uml("far", "a", "b", "c"),
    uml("wrap a"),
    uml("wrap a", "{{uml", "x", "}}"),
    "@startuml\n!define X 1\n!if a\n!else\n!endif\nalpha x\n@enduml",
    "@startuml\n!procedure p()\nalpha x\n!endprocedure\n@enduml",
]
TOYS_CASES = [
    *(Case(text) for text in TOYS_BLOCKS),
    Case(uml("title hi"), {START: ["classtoy", "seqtoy"]}),
    Case(uml("title hi"), {"@startuml": ["classtoy"]}),
    Case(uml("alpha x"), {"salt": ["seqtoy"]}),
    Case(uml("alpha x"), {START: ["ghost"]}),
]


def build_toys(tmp: Path) -> ResolvedModels:
    return resolve(load_dir(INTERP_FIXTURES))


# --- dispatch: test_document_dispatch.py ----------------------------------------------------

DISPATCH_CASES = [
    *(Case(uml(line)) for line in ["seq a", "cls x", "act y", "act3 y", "clsfamily z", "nope"]),
    Case("@startmindmap\nmind x\n@endmindmap"),
    Case("@startumlish\nseq a\n@endumlish"),
    Case("@startfoo\nseq\n@endfoo"),
    Case(uml("cls x"), {START: ["ClassF", "seq", "ghost"]}),
    Case(uml("cls x"), {START: ["doc"]}),
    Case("cls x"),
]


def build_dispatch(tmp: Path) -> ResolvedModels:
    return dispatch_toys.family()


# --- empty: empty_models() in test_document_dispatch.py -------------------------------------

EMPTY_ANY = [{**dispatch_toys.ANY, "parts": {"regex": ".*"}}]
EMPTY_WELCOME = [
    dispatch_toys.rule("Blank", "", set="dead"),
    dispatch_toys.rule("Welcome", dispatch_toys.END_LINE["regex"]),
]
EMPTY_BLOCKS = [
    uml(),
    uml("", "' comment"),
    uml("x"),
    uml(""),
    "",
    "@startuml",
    "@startuml\n@enduml",
]
EMPTY_IDS = ("e1", "e2", "e3")


def build_empty(tmp: Path) -> ResolvedModels:
    models: ResolvedModels = {}
    specs = [("e1", {"empty": EMPTY_ANY}), ("e2", {"empty": EMPTY_WELCOME, "dead": []}), ("e3", {})]
    for index, (mid, extra) in enumerate(specs, start=1):
        contexts = {"main": [], **extra}
        models[mid] = dispatch_toys.diagram(mid, f"EF{index}", "SEQUENCE", contexts=contexts)
    return models


EMPTY_CASES = [raw_text(mid, text) for mid in EMPTY_IDS for text in EMPTY_BLOCKS]

# --- plain-lines: test_plain_lines_empty_end.py ---------------------------------------------

STYLE_JOIN = (
    "    - command: Style\n      provenance: {class: t.Style}\n      kind: multiline\n"
    f"      join: {{max_lines: 10}}\n      parts: {{regex: '{plain_toys.STYLE}'}}\n"
)


def style_yaml(mid: str, factory: str) -> str:
    body = "contexts:\n  main:\n" + STYLE_JOIN + plain_toys.entry("Tail", "tail")
    return header(mid, f"factory: {factory}\n") + body


def welcome_yaml(mid: str, factory: str, needs_end: bool) -> str:
    key = "empty_needs_end: true\n" if needs_end else ""
    end = plain_toys.entry("EndLine", "[@\\\\]end.*")
    return header(mid, f"factory: {factory}\n{key}") + "contexts:\n  main: []\n  empty:\n" + end


PLAIN_FILES = {
    "style-cmd": style_yaml("style-cmd", "ClassDiagramFactory"),
    "style-plain": style_yaml("style-plain", "JsonDiagramFactory"),
    "welcome": welcome_yaml("welcome", "PSystemWelcomeFactory", False),
    "welcome-strict": welcome_yaml("welcome-strict", "PSystemCharlieFactory", True),
}
GLUED = ("<style>", "{{", "a", "</style>", "tail")
PLAIN_CASES = [
    *(on(mid, *GLUED) for mid in ("style-cmd", "style-plain")),
    on("style-plain", "<style>", "{{", "a"),
    on("style-cmd", "<style>", "a", "</style>", "tail"),
    *(raw_text(mid, text) for mid in ("welcome", "welcome-strict") for text in EMPTY_BLOCKS),
    *(on(mid, "x") for mid in ("welcome", "welcome-strict")),
]

# --- require-pop: test_require_pop_reject.py ------------------------------------------------

RP = ", require_pop: true"
NOPE = "    - {command: Nope, provenance: {class: t.Nope}, kind: single, parts: {regex: 'zzz'}}\n"
BOTTOM_POP = (
    "    - {command: P, provenance: {class: t.P}, kind: single, parts: {regex: p}, pop: true}\n"
)
SW_BODY = """
  body:
    - {command: Sw, provenance: {class: t.Sw}, kind: single, parts: {regex: sw}, set: other}
  other:
    - {command: Close, provenance: {class: t.Close}, kind: single, parts: {regex: '\\}'}, pop: true}
"""
BAD_BODY = """
  body:
    - {command: Close, provenance: {class: t.Close}, kind: single, parts: {regex: '\\}'}, pop: true}
    - {command: Bad, provenance: {class: t.Bad}, kind: single, parts: {regex: bad}, reject: true}
    - {command: Item, provenance: {class: t.Item}, kind: single, parts: {regex: '\\w+'}}
"""
TOP_YAML = """schema_version: 1
id: rj-top
layer: diagram
diagram: CLASS
include: [rj-base]
insert_before:
  Page:
    - {command: Zero, provenance: {class: t.Zero}, kind: single,
       parts: {regex: 'page 0'}, reject: true}
"""


def pop_yaml(mid: str, main: str, body: str = pop_toys.BODY) -> str:
    return header(mid) + "contexts:\n  main:\n" + main + body


def pop_files() -> dict[str, str]:
    open_pop = pop_toys.OPEN % RP
    files = {
        "rp-open": pop_yaml("rp-open", pop_toys.WORD + open_pop),
        "rp-plain": pop_yaml("rp-plain", pop_toys.WORD + pop_toys.OPEN % ""),
        "rp-fallback": pop_yaml("rp-fallback", pop_toys.WORD + open_pop + pop_toys.PLAIN),
        "rp-nope": pop_yaml("rp-nope", pop_toys.WORD + open_pop + NOPE),
        "rp-bottom": pop_yaml("rp-bottom", BOTTOM_POP + pop_toys.WORD + open_pop),
        "rp-set": pop_yaml("rp-set", pop_toys.WORD + open_pop, SW_BODY),
        "rj-catch": pop_yaml("rj-catch", pop_toys.PAGE + pop_toys.CATCH_ALL),
        "rj-reject": pop_yaml("rj-reject", pop_toys.REJECT + pop_toys.PAGE + pop_toys.CATCH_ALL),
        "rj-first": pop_yaml("rj-first", pop_toys.REJECT + pop_toys.CATCH_ALL),
        "rj-later": pop_yaml("rj-later", pop_toys.PAGE.replace("\\d+", "0") + pop_toys.REJECT),
        "rj-body": pop_yaml("rj-body", pop_toys.WORD + pop_toys.OPEN % "", BAD_BODY),
    }
    base = pop_yaml("rj-base", pop_toys.PAGE + pop_toys.CATCH_ALL)
    files["rj-base"] = base.replace("layer: diagram", "layer: shared").replace(
        "diagram: CLASS\n", ""
    )
    files["rj-top"] = TOP_YAML
    return files


POP_CASES = [
    on("rp-plain", "open {", "a", "b"),
    on("rp-open", "ok", "open {", "a", "b"),
    on("rp-open", "open {", "a", "}", "c"),
    on("rp-open", "open {"),
    on("rp-fallback", "open {", "a", "b"),
    on("rp-fallback", "open {", "inner {", "x", "}"),
    on("rp-nope", "open {", "a"),
    on("rp-open", "open {", "inner {", "x", "}"),
    on("rp-open", "open {", "inner {", "x", "}", "}"),
    on("rp-open", "open {", "inner {", "x"),
    on("rp-open", "open {", "}", "open {", "a"),
    on("rp-bottom", "p", "open {", "}"),
    on("rp-bottom", "p", "open {"),
    on("rp-set", "open {", "sw", "}"),
    on("rp-set", "open {", "sw"),
    on("rj-catch", "page 0"),
    on("rj-reject", "x", "page 0"),
    on("rj-reject", "page 3", "anything"),
    on("rj-later", "page 0"),
    on("rj-body", "open {", "ok", "bad", "}"),
    on("rj-top", "page 0"),
    on("rj-top", "page 1"),
    on("rj-first", "page 0"),
    on("rj-first", "x", "page 0"),
]

# --- flags: test_flags_trim.py --------------------------------------------------------------

F = flags_toys
PRE_YAML = (
    "schema_version: 1\nid: pre\nlayer: preproc\ncontexts:\n  main:\n"
    + F.single("PreTask", "!task", gives=F.FLAG)
    + F.single("PreSep", "!sep", needs=F.FLAG)
)
OTHER = F.single("Other", "other", gives="something_else")
BAD = F.single("Bad", "bad", reject="true", gives=F.FLAG)


def flag_yaml(mid: str, main: str, *contexts: str) -> str:
    return header(mid) + "contexts:\n  main:\n" + main + "".join(contexts)


def flag_files() -> dict[str, str]:
    sep_task = F.SEP + F.TASK
    open_rules = F.OPEN + F.PLAIN + F.ANY
    return {
        "pre": PRE_YAML,
        "fl-sep-task": flag_yaml("fl-sep-task", sep_task),
        "fl-other": flag_yaml("fl-other", F.SEP + OTHER),
        "fl-group": flag_yaml("fl-group", F.SEP + F.GROUP + F.TASK, F.GROUP_CTX),
        "fl-open": flag_yaml("fl-open", F.SEP + open_rules, F.BODY_CTX),
        "fl-open-task": flag_yaml("fl-open-task", sep_task + open_rules, F.BODY_CTX),
        "fl-open-nosep": flag_yaml("fl-open-nosep", open_rules, F.BODY_CTX),
        "fl-bad": flag_yaml("fl-bad", F.SEP + BAD + F.ANY),
        "fl-plus": flag_yaml("fl-plus", F.PLUS),
        "fl-plus-any": flag_yaml("fl-plus-any", F.PLUS + F.ANY),
        "fl-plus-dash": flag_yaml("fl-plus-dash", F.PLUS + F.DASH),
        "fl-dash-ovr": header("fl-dash-ovr", "overrides:\n  Dash: {trim: false}\n")
        + "contexts:\n  main:\n"
        + F.DASH,
    }


FLAG_CASES = [
    on("fl-sep-task", "-- a --"),
    on("fl-sep-task", "-- a --", "task x"),
    on("fl-sep-task", "task x", "-- a --"),
    on("fl-sep-task", "task x"),
    on("fl-sep-task", "-- a --", "-- b --", "task x"),
    on("fl-sep-task", "-- a --", "nope"),
    on("fl-other", "-- a --", "other"),
    on("fl-group", "-- a --", "grp {", "task x", "}"),
    on("fl-group", "grp {", "}"),
    on("fl-open", "-- a --", "open {", "task x"),
    on("fl-open-task", "-- a --", "task x", "open {", "task y"),
    on("fl-open-nosep", "open {", "-- a --"),
    on("fl-open", "-- a --", "open {", "task x", "}"),
    on("fl-bad", "-- a --", "bad"),
    raw_text("fl-sep-task", "@startuml\n-- a --"),
    on("fl-sep-task", "!task", "-- a --"),
    on("fl-sep-task", "!sep", "task x"),
    *(on("fl-plus", line) for line in ["++ b", "  ++ b", "\t++ b", "++ b ", "++ b\t", " ++ b"]),
    on("fl-plus-dash", "  -- b  ", "\t-- c"),
    raw_text("fl-plus", "@startuml\r\n++ b\r\n@enduml\r\n"),
    on("fl-plus-any", "  ++ b"),
    on("fl-dash-ovr", "-- b"),
    on("fl-dash-ovr", " -- b"),
]

TOY_SPECS = [
    ToySpec("toys", build_toys, [Case(c.text, c.start_map) for c in TOYS_CASES]),
    ToySpec("dispatch", build_dispatch, DISPATCH_CASES),
    ToySpec("empty", build_empty, EMPTY_CASES),
    ToySpec("plain-lines", from_yaml(PLAIN_FILES), PLAIN_CASES),
    ToySpec("require-pop", from_yaml(pop_files()), POP_CASES),
    ToySpec("flags", from_yaml(flag_files()), FLAG_CASES),
]
