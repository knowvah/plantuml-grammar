"""board, files and git diagrams (T31, ``model/diagrams/board-files-git-*.yaml``).

``board-files-git-board`` extends ``gen-board-diagram`` and ``common``: CommandBoardPlus is
narrowed to activity lines (``set: board_activities``) and followed by a reject of the
release shape; ``board_activities`` takes releases with a head entry.

``board-files-git-files`` and ``board-files-git-git`` replace the opaque T13 models of
the two non-command factories. Files rejects only a style stream whose first failure is
not a StyleParsingException; ``files_verdict`` below is a reference implementation of
StyleExtractor + StyleParser (oracle-checked in ``test_reference_equals_the_jar``) that
the model is compared with. Git rejects a line whose first ``*`` is not followed by a
space or ``-``.

Fixtures (``tests/fixtures/board-files-git``), each with a header before ``@start``::

    ' board-files-git: RuleA, RuleB    rule ids the fixture exercises
    ' gap: <reason>                    gap/ only: why the model gets it wrong
    ' jar: accept|reject               gap/ only: the jar's verdict
"""

from __future__ import annotations

import random
import re
from pathlib import Path
from typing import Any

import pytest

from tools.interp import accepts
from tools.interp.compile import compile_part
from tools.interp.source import split_blocks
from tools.model import Model, ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve, top_models

REPO = Path(__file__).resolve().parents[2]
MODEL_DIR = REPO / "model"
FIXTURES = REPO / "tests" / "fixtures" / "board-files-git"
POS, NEG, GAP = "pos", "neg", "gap"
BOARD_ID, FILES_ID, GIT_ID = "board-files-git-board", "board-files-git-files", "board-files-git-git"
FAMILY_IDS = (BOARD_ID, FILES_ID, GIT_ID)
FACTORIES = {
    BOARD_ID: ("BoardDiagramFactory", "BOARD", ["gen-board-diagram", "common"]),
    FILES_ID: ("FilesDiagramFactory", "FILES", ["embedded-files", "style", f"{FILES_ID}-style"]),
    GIT_ID: ("GitDiagramFactory", "GIT", ["embedded-git"]),
}
UPSTREAM_PREFIX = "src/main/java/net/sourceforge/plantuml/"
HEADER_IGNORED = ("!assume ", "!pragma ", "hide ", "scale ", "title ", "skin ")
HEADER = re.compile(r"^' (?P<key>board-files-git|gap|jar): (?P<value>.+)$")
BOARD_PLUS, BOARD_RELEASE, BOARD_REJECT = (
    "CommandBoardPlus",
    "BoardRelease",
    "BoardReleaseWithoutActivity",
)
STYLE_REJECT = "CommandStyleMultilinesCSSReject"
# Upstream generated regex of CommandBoardPlus.java:54-58 (`%s` expanded).
BOARD_PLUS_JAVA = re.compile("([+]*)[\\s ]*([^\\s ].*)")
# Emitter-view entries the interpreter never selects (an earlier entry always takes the line).
EMIT_ONLY = {"FilesStyleStructure", "CommandStyleMultilinesCSSStructure"}
EMIT_ONLY |= {"FilesEntryView", "FilesNoteView", "FilesOtherLineView"}
STYLE_TAGS = ("<style>", "</style>")
TRIN = "".join(chr(c) for c in range(33))


@pytest.fixture(scope="module")
def raw_models() -> dict[str, Model]:
    return load_dir(MODEL_DIR)


@pytest.fixture(scope="module")
def models(raw_models: dict[str, Model]) -> ResolvedModels:
    return resolve(raw_models)


def commands(entries: list[dict[str, Any]]) -> list[str]:
    return [e["command"] for e in entries if "command" in e]


def entry(models: ResolvedModels, mid: str, context: str, command: str) -> dict[str, Any]:
    (found,) = [e for e in models[mid].contexts[context] if e.get("command") == command]
    return found


def fullmatch(part: Any, text: str) -> bool:
    return compile_part(part).fullmatch(text) is not None


def block(keyword: str, body: list[str]) -> str:
    return f"@start{keyword}\n" + "".join(f"{line}\n" for line in body) + f"@end{keyword}\n"


# --- the models -----------------------------------------------------------------------


@pytest.mark.parametrize("mid", FAMILY_IDS)
def test_family_model_is_the_top_model_of_its_factory(
    raw_models: dict[str, Model], models: ResolvedModels, mid: str
) -> None:
    factory, diagram, include = FACTORIES[mid]
    raw = raw_models[mid]
    assert (raw.layer, raw.diagram, raw.factory, raw.include) == (
        "diagram",
        diagram,
        factory,
        include,
    )
    assert top_models(models)[factory] == mid


@pytest.mark.parametrize("mid", (FILES_ID, GIT_ID))
def test_opaque_bases_are_shadowed(models: ResolvedModels, mid: str) -> None:
    kinds = {e["kind"] for es in models[mid].contexts.values() for e in es if "kind" in e}
    assert "opaque" not in kinds


def test_board_plus_is_narrowed_and_followed_by_its_reject(models: ResolvedModels) -> None:
    main = commands(models[BOARD_ID].contexts["main"])
    at = main.index(BOARD_PLUS)
    assert main[at + 1] == BOARD_REJECT
    plus = entry(models, BOARD_ID, "main", BOARD_PLUS)
    assert (plus["set"], plus["trim"]) == ("board_activities", False)
    reject = entry(models, BOARD_ID, "main", BOARD_REJECT)
    assert (reject["reject"], reject["trim"]) == (True, False)
    activities = commands(models[BOARD_ID].contexts["board_activities"])
    assert activities[0] == BOARD_RELEASE
    assert activities[1:] == main


def test_board_style_reject_is_redefined(models: ResolvedModels) -> None:
    main = commands(models[BOARD_ID].contexts["main"])
    at = main.index("CommandStyleMultilinesCSS")
    assert main[at + 1 : at + 3] == [STYLE_REJECT, "CommandStyleMultilinesCSSStructure"]
    check = entry(models, BOARD_ID, "main", STYLE_REJECT)
    assert (check["kind"], check["emit"]) == ("single", False)
    assert (check["push"], check["require_pop"]) == ("board_style_bad", True)


def random_lines(alphabet: list[str], count: int, seed: int) -> list[str]:
    rng = random.Random(seed)
    return ["".join(rng.choice(alphabet) for _ in range(rng.randint(0, 6))) for _ in range(count)]


BOARD_LINES = random_lines(["+", " ", "\t", " ", "a", "x+"], 3000, 31)


def test_activity_and_release_partition_the_generated_rule(models: ResolvedModels) -> None:
    activity = entry(models, BOARD_ID, "main", BOARD_PLUS)["parts"]
    release = entry(models, BOARD_ID, "board_activities", BOARD_RELEASE)["parts"]
    for line in BOARD_LINES:
        java = BOARD_PLUS_JAVA.fullmatch(line)
        want_activity = java is not None and java[1] == ""
        want_release = java is not None and java[1] != ""
        assert fullmatch(activity, line) is want_activity, repr(line)
        assert fullmatch(release, line) is want_release, repr(line)


def test_no_earlier_command_takes_a_release_line(models: ResolvedModels) -> None:
    main = models[BOARD_ID].contexts["main"]
    earlier = main[: commands(main).index(BOARD_PLUS)]
    releases = [line for line in BOARD_LINES if line.startswith("+") and line[1:].strip(" \t ")]
    assert len(releases) > 100
    for e in earlier:
        for line in releases:
            text = line if e.get("trim") is False else line.strip(TRIN)
            assert not fullmatch(e["parts"], text), (e["command"], line)


GIT_LINES = random_lines(["*", " ", "-", "\t", "|", "/", "a", "("], 3000, 7)


def test_git_line_entries_accept_exactly_good_commit_lines(models: ResolvedModels) -> None:
    main = models[GIT_ID].contexts["main"]
    for line in GIT_LINES:
        star = line.find("*")
        want = star == -1 or line[star + 1 : star + 2] in (" ", "-")
        got = any(fullmatch(e["parts"], line) for e in main)
        assert (got or not line.strip(TRIN)) is want, repr(line)  # blank lines are skipped


def hand_written(raw_models: dict[str, Model]) -> list[dict[str, Any]]:
    out = [e for mid in FAMILY_IDS for es in raw_models[mid].contexts.values() for e in es]
    out += [e for es in raw_models[BOARD_ID].insert_after.values() for e in es]
    return [e for e in out if "command" in e]


def test_hand_written_entries_cite_upstream_file_and_line(raw_models: dict[str, Model]) -> None:
    entries = hand_written(raw_models)
    assert len(entries) == 37
    for e in entries:
        prov = e["provenance"]
        assert prov["file"].startswith(UPSTREAM_PREFIX), e["command"]
        assert prov["line"] >= 1, e["command"]


# --- files: reference implementation of the style stream -------------------------------


def trin(text: str) -> str:
    return text.strip(TRIN)


def extract_style(body: list[str]) -> list[str]:
    """jsondiagram/StyleExtractor.java:63-103 (its iterator includes `@start`/`@end`)."""
    src, style, listed = ["@startfiles", *body, "@endfiles"], [], 0
    i = 0
    while i < len(src):
        line, i = src[i], i + 1
        s = trin(line)
        if not s:
            continue
        if s == "<style>":
            while i < len(src):
                style.append(line)
                if s == "</style>":
                    break
                line, i = src[i], i + 1
                s = trin(line)
        elif listed <= 1 and s.startswith(HEADER_IGNORED):
            continue
        elif listed <= 1 and s.startswith("skinparam "):
            while "{" in s and i < len(src) and trin(line) != "}":
                line, i = src[i], i + 1
        else:
            listed += 1
    return style


def tokenize(lines: list[str]) -> list[tuple[str, str]]:
    """StyleParser.java:240-360 over trimmed lines + "\\n" (CharInspectorImpl.java:51-79)."""
    text, out, pos = "".join(trin(x) + "\n" for x in lines), [], 0
    while pos < len(text):
        c, two = text[pos], text[pos : pos + 2]
        if c in " \t":
            pos += 1
        elif two == "//":
            pos = text.find("\n", pos) + 1 or len(text)
        elif two in ("/*", "/'"):
            end = text.find(two[1] + "/", pos + 1)
            pos = len(text) if end < 0 else end + 2
        elif c in ",;*:{}\n":
            out.append(("N" if c == "\n" else c, c))
            pos += 1
        elif c in '@"':
            stop = re.compile("[{};]" if c == "@" else '"').search(text, pos + 1)
            end = stop.start() if stop else len(text)
            out.append(("S" if c == '"' else "@", text[pos + 1 : end]))
            pos = end + 1
        else:
            word = re.compile(r"\.[^\n{};,:\t]*|[^ \n{};,:\t]+").match(text, pos)[0]
            out.append(("S", word.strip(TRIN) if c == "." else word))
            pos += len(word)
    return out


class Crash(Exception):
    """An exception other than StyleParsingException (the jar rejects)."""


class Stop(Exception):
    """StyleParsingException: swallowed by FilesDiagram.java:66-70."""


class Peeker:
    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self.tokens, self.pos = tokens, 0

    def type(self, ahead: int = 0) -> str:
        if self.pos + ahead >= len(self.tokens):
            raise Crash("NullPointerException")
        return self.tokens[self.pos + ahead][0]

    def has(self) -> bool:
        return self.pos < len(self.tokens)

    def skip(self, kinds: str) -> None:
        while self.has() and self.type() in kinds:
            self.pos += 1


def read_value(p: Peeker) -> None:
    """StyleParser.java:190-219."""
    while p.has() and p.type() not in "N;}":
        kind = p.type()
        if kind not in "S,:":
            raise Stop
        p.pos += 1
        if kind == ":":
            if p.type() != "S":
                raise Stop
            p.pos += 1


def statement(p: Peeker, kind: str, data: str) -> None:
    """One iteration of parseNow (StyleParser.java:91-174) after its first token."""
    if p.type() == ",":
        p.skip("S,")
        p.skip("N")
        if p.type() != "{":
            raise Crash("IllegalStateException")
        p.pos += 1
    elif kind == "S":
        if p.type() == "*":
            p.pos += 1
        p.skip("N")
        if p.type() == "{":
            p.pos += 1
            return
        p.skip(":")
        if not data.startswith("--") and p.type() != "S":
            raise Stop
        read_value(p)
    elif kind == ":" and p.type() == "S" and p.type(1) == "{":
        p.pos += 2
    elif kind == ":" and p.type() == "S" and p.type(1) == "*" and p.type(2) == "{":
        p.pos += 3
    elif kind == "{":
        raise Stop
    elif kind not in "}@":
        raise Crash("IllegalStateException")


def files_verdict(body: list[str]) -> str:
    """``ok``, ``stop`` (StyleParsingException) or ``crash`` for a files diagram body."""
    p = Peeker(tokenize(extract_style(body)))
    try:
        while p.has():
            kind, data = p.tokens[p.pos]
            p.pos += 1
            if kind not in "N;" and not (kind == "S" and data.lower() in STYLE_TAGS):
                statement(p, kind, data)
    except Crash:
        return "crash"
    except Stop:
        return "stop"
    return "ok"


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        (["<style>", "*", "</style>"], "crash"),
        (["<style>", "a,b", "</style>"], "crash"),
        (["<style>", "{", "</style>"], "stop"),
        (["<style>", "root {"], "ok"),
        (["<style>", "foo:", "</style>"], "stop"),
        (["  <style>", "*", "  </style>"], "crash"),
        (["<style>", "a,", "</style>", "x", "<style>", "b {", "}", "</style>"], "crash"),
        (["skinparam foo {", "<style>", "*", "}"], "ok"),
        (["/a", "skinparam foo {", "<style>", "*", "</style>", "}"], "crash"),
        (["<style>", ":x", "</style>"], "crash"),
        (["<style>", "--x: a:", "</style>"], "stop"),
        (["<style>", "root", "/* x"], "crash"),
        (["<style>", "root { FontColor red } // c", "</style>"], "ok"),
    ],
)
def test_reference_examples(body: list[str], expected: str) -> None:
    assert files_verdict(body) == expected


STYLE_FRAGMENTS = ["a", "root", "--v", ".x y", '"q"', '"', "*", ",", ":", ";", "{", "}"]
STYLE_FRAGMENTS += ["@media d {", "@m", "//c", "FontColor", "red", "<STYLE>", "x:y", "b,c"]
HEAD_LINES = ["title t", "skinparam x {", "}", "/a", "hide x", "", "<note>"]


def random_style_body(rng: random.Random, fragments: list[str]) -> list[str]:
    head = [rng.choice(HEAD_LINES) for _ in range(rng.choice([0, 0, 1, 2]))]
    lines = [
        (" " * rng.choice([0, 1, 2])).join(rng.choice(fragments) for _ in range(rng.randint(0, 4)))
        for _ in range(rng.randint(0, 5))
    ]
    closed = rng.random() < 0.7
    if not closed and lines and "//" in lines[-1]:
        lines.pop()  # gap/files-unterminated-value-trailing-comment
    tail = ["</style>", rng.choice(["/a", "x", ""])] if closed else []
    return head + [rng.choice(["<style>", " <style> "])] + lines + tail


def test_model_equals_the_reference_on_single_blocks(models: ResolvedModels) -> None:
    rng, seen = random.Random(1031), set()
    for _ in range(1500):
        body = random_style_body(rng, STYLE_FRAGMENTS)
        if sum(trin(x) == "<style>" for x in extract_style(body)) != 1:
            continue
        want = files_verdict(body)
        seen.add(want)
        got = accepts(models, block("files", body))
        assert got["accepted"] is (want != "crash"), (body, want)
    assert seen == {"ok", "stop", "crash"}


@pytest.mark.corpus
def test_reference_equals_the_jar(tmp_path: Path) -> None:
    from tools.validate.oracle import oracle_verdicts

    rng = random.Random(2031)
    paths = []
    for k in range(300):
        body = random_style_body(rng, [*STYLE_FRAGMENTS, "/*", "*/", "/*c*/"])
        body += [rng.choice(["<style>", "x"]), *random_style_body(rng, STYLE_FRAGMENTS)]
        path = tmp_path / f"f{k}.puml"
        path.write_text(block("files", body), encoding="utf-8")
        paths.append(path)
    verdicts = oracle_verdicts(paths)
    for path in paths:
        (got,) = verdicts[str(path)]
        assert got["accepted"] is (files_verdict(got["preproc"][1:-1]) != "crash"), path.read_text()


# --- fixtures -------------------------------------------------------------------------


def fixtures(group: str) -> list[Path]:
    return sorted((FIXTURES / group).glob("*.puml"))


def header(path: Path) -> dict[str, str]:
    found = (HEADER.match(line) for line in path.read_text(encoding="utf-8").splitlines())
    return {m["key"]: m["value"] for m in found if m}


def fixture_commands(path: Path) -> list[str]:
    return [c.strip() for c in header(path)["board-files-git"].split(",")]


def jar_accepts(path: Path) -> bool:
    group = path.parent.name
    return group == POS if group != GAP else header(path)["jar"] == "accept"


def rel(path: Path) -> str:
    return path.relative_to(FIXTURES).as_posix()


def run(models: ResolvedModels, path: Path) -> Any:
    (found,) = split_blocks(path.read_text(encoding="utf-8"))
    return accepts(models, found, raw=True)


@pytest.mark.parametrize("path", fixtures(POS), ids=rel)
def test_pos_fixture_is_accepted(models: ResolvedModels, path: Path) -> None:
    got = run(models, path)
    assert got["accepted"], got["first_failure"]
    assert got["model"] in FAMILY_IDS


@pytest.mark.parametrize("path", fixtures(NEG), ids=rel)
def test_neg_fixture_is_rejected(models: ResolvedModels, path: Path) -> None:
    assert run(models, path)["accepted"] is False


def gap_params() -> list[Any]:
    return [
        pytest.param(p, id=rel(p), marks=pytest.mark.xfail(strict=True, reason=header(p)["gap"]))
        for p in fixtures(GAP)
    ]


@pytest.mark.parametrize("path", gap_params())
def test_gap_fixture_matches_the_jar(models: ResolvedModels, path: Path) -> None:
    assert run(models, path)["accepted"] is jar_accepts(path)


def test_every_hand_written_rule_has_a_fixture(raw_models: dict[str, Model]) -> None:
    covered = {c for p in fixtures(POS) + fixtures(NEG) for c in fixture_commands(p)}
    wanted = {e["command"] for e in hand_written(raw_models)} - EMIT_ONLY
    assert wanted - covered == set()


def test_every_fixture_names_known_rules(models: ResolvedModels) -> None:
    known = {c for mid in FAMILY_IDS for es in models[mid].contexts.values() for c in commands(es)}
    for path in fixtures(POS) + fixtures(NEG) + fixtures(GAP):
        assert set(fixture_commands(path)) <= known, rel(path)


@pytest.mark.corpus
def test_fixture_verdicts_equal_the_oracle() -> None:
    from tools.validate.oracle import oracle_verdicts

    paths = fixtures(POS) + fixtures(NEG) + fixtures(GAP)
    verdicts = oracle_verdicts(paths)
    for path in paths:
        (got,) = verdicts[str(path)]
        assert got["accepted"] is jar_accepts(path), rel(path)
        if got["accepted"]:
            assert got["diagram_type"] in ("BOARD", "FILES", "GIT"), rel(path)


def test_files_emitter_view_is_flat(raw_models: dict[str, Model]) -> None:
    visible = [
        e
        for es in raw_models[FILES_ID].contexts.values()
        for e in es
        if "command" in e and e.get("emit") is not False
    ]
    pushing = [e["command"] for e in visible if {"push", "set", "pop"} & set(e)]
    assert set(pushing) == {"FilesStyleStructure", "FilesSkinparamSkipEnd"}
