"""End-to-end: UBrex challenge trees and the gantt sentence dump (needs jar and upstream clone)."""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from tools.config import PIN_SHA, require
from tools.extract import build, run

pytestmark = pytest.mark.corpus

GANTT_DIR = "src/main/java/net/sourceforge/plantuml/gantt"
FACTORY_PATH = f"{GANTT_DIR}/GanttDiagramFactory.java"
VERBS_PATH = f"{GANTT_DIR}/lang/Verbs.java"
LANG_DIR = f"{GANTT_DIR}/lang"
NATURAL_REASON_PREFIX = "natural-gantt-sentence"
IF_CLASS = "net.sourceforge.plantuml.activitydiagram.command.UBrexCommandIf"
HIDE_SHOW_CLASS = "net.sourceforge.plantuml.classdiagram.command.UBrexCommandHideShow2"
LANG_PACKAGE = "net.sourceforge.plantuml.gantt.lang."
PROBE_CLASS = "UBrexProbe"
PROBE_SOURCE = """
import com.plantuml.ubrex.UnicodeBracketedExpression;
import java.util.LinkedHashMap;
import java.util.Map;

public class UBrexProbe {
    public static void main(String[] args) {
        Map<String, Object> out = new LinkedHashMap<>();
        for (String a : args) {
            out.put(a, new UBrexWalker().walk(UnicodeBracketedExpression.build(a)));
        }
        System.out.println(Json.compact(out));
    }
}
"""


def _git_show(path: str) -> str:
    return subprocess.run(
        ["git", "-C", str(require("src")), "show", f"{PIN_SHA}:{path}"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def _classpath() -> str:
    return os.pathsep.join([str(require("jar")), str(build.REPO_ROOT / build.OUT_DIR)])


def _pin_props() -> list[str]:
    pin = run.load_pin(build.REPO_ROOT)
    return [f"-Dpin.sha={pin['sha']}", f"-Dpin.version={pin['version']}"]


@pytest.fixture(scope="module")
def out_dir(tmp_path_factory) -> Path:
    out = tmp_path_factory.mktemp("ubrex-out")

    def runner(cmd: list[str]) -> int:
        return subprocess.run(cmd, capture_output=True, check=False).returncode

    assert run.run_extractor(out=out, run=runner) == 0
    dump = ["java", *_pin_props(), "-cp", _classpath(), "GanttLangDump", str(out)]
    assert subprocess.run(dump, capture_output=True, check=False).returncode == 0
    return out


@pytest.fixture(scope="module")
def docs(out_dir) -> dict[str, dict]:
    return {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in out_dir.glob("*.json")
        if p.stem != "gantt-lang"
    }


@pytest.fixture(scope="module")
def gantt(out_dir) -> dict:
    return json.loads((out_dir / "gantt-lang.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def probe(tmp_path_factory):
    """Walk synthetic UBrex strings with the real walker; returns {ubrex: Node}."""
    work = tmp_path_factory.mktemp("probe")
    (work / f"{PROBE_CLASS}.java").write_text(PROBE_SOURCE, encoding="utf-8")
    cp = _classpath()
    subprocess.run(
        ["javac", "-cp", cp, "-d", str(work), str(work / f"{PROBE_CLASS}.java")],
        check=True,
        capture_output=True,
    )

    def walk(*ubrex: str) -> dict:
        cmd = ["java", "-cp", f"{cp}{os.pathsep}{work}", PROBE_CLASS, *ubrex]
        done = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return json.loads(done.stdout)

    return walk


def _all_commands(docs):
    return [(d["factory"], c) for d in docs.values() for c in d["commands"]]


def _first_leaf(node: dict) -> dict:
    return node if not node["children"] else _first_leaf(node["children"][0])


def _inner(node: dict) -> dict:
    """The single operand under the CompositeList root the parser wraps around."""
    assert node["t"] == "ub-CompositeList"
    return node["children"][0]


def test_ubrex_command_if_has_ub_tree(docs):
    cmd = next(c for c in docs["ActivityDiagramFactory"]["commands"] if c["class"] == IF_CLASS)
    assert cmd["engine"] == "UBrex"
    assert cmd["kind"] == "single"
    assert cmd["start"]["t"].startswith("ub-")
    assert cmd["start"]["t"] == "ub-CompositeList"


def test_no_unreachable_entry_is_ubrex_pending(docs):
    reasons = {u["reason"] for d in docs.values() for u in d["unreachable"]}
    assert "ubrex-pending" not in reasons
    assert reasons <= {"opaque-no-regex-field"} | {
        r for r in reasons if r.startswith(NATURAL_REASON_PREFIX)
    }


def test_every_ubrex_command_has_tree_except_natural_gantt(docs):
    ubrex = [(f, c) for f, c in _all_commands(docs) if c["engine"] == "UBrex"]
    assert len(ubrex) == 23
    natural = [c for _, c in ubrex if c["class"].endswith(".NaturalGanttCommand")]
    assert len(natural) == 9
    assert all(c["start"] is None for c in natural)
    others = [c for _, c in ubrex if c not in natural]
    assert len(others) == 14
    assert all(c["start"]["t"].startswith("ub-") for c in others)


def test_natural_gantt_unreachable_points_at_gantt_lang(docs):
    entries = [
        u
        for u in docs["GanttDiagramFactory"]["unreachable"]
        if u["class"].endswith(".NaturalGanttCommand")
    ]
    assert len(entries) == 9
    assert {u["reason"] for u in entries} == {
        "natural-gantt-sentence: grammar is the subject x verb-phrase composition "
        "in extracted/gantt-lang.json"
    }


def test_ubrex_multiline_end_is_walked(docs):
    multi = [
        c for _, c in _all_commands(docs) if c["engine"] == "UBrex" and c["kind"] == "multiline"
    ]
    assert len(multi) == 1
    assert multi[0]["start"]["t"].startswith("ub-")
    assert multi[0]["end"]["t"].startswith("ub-")


def test_named_capture_recorded(docs):
    cmd = next(c for _, c in _all_commands(docs) if c["class"] == HIDE_SHOW_CLASS)
    names = []

    def collect(n):
        if n["name"]:
            names.append(n["name"])
        for k in n["children"]:
            collect(k)

    collect(cmd["start"])
    assert names[0] == "COMMAND"
    assert all(isinstance(n, str) for n in names)


@pytest.mark.parametrize(
    ("ubrex", "direction", "negated", "look"),
    [
        ("〒=a", "ahead", False, "LOOK_AHEAD_POSITIVE"),
        ("〒!a", "ahead", True, "LOOK_AHEAD_NEGATIVE"),
        ("〒<=a", "behind", False, "LOOK_BEHIND_POSITIVE"),
        ("〒<!a", "behind", True, "LOOK_BEHIND_NEGATIVE"),
    ],
)
def test_lookaround_records_direction_and_negation(probe, ubrex, direction, negated, look):
    node = _inner(probe(ubrex)[ubrex])
    assert node["t"] == (
        "ub-ChallengeLookAhead" if direction == "ahead" else "ub-ChallengeLookBehind"
    )
    assert (node["direction"], node["negated"], node["lookAround"]) == (direction, negated, look)
    assert node["children"][0]["pattern"] == "a"


def test_leaf_and_quantifier_nodes(probe):
    got = probe("〒$", "A", "〇?a", "〇+a", "〇*a", "〴s", "〴D")
    assert _inner(got["〒$"])["t"] == "ub-ChallengeEndOfText"
    single = _inner(got["A"])
    assert (single["t"], single["pattern"], single["caseMode"]) == (
        "ub-ChallengeSingleChar",
        "a",
        "CASE_INSENSITIVE",
    )
    for src, t in (("〇?a", "Optional"), ("〇+a", "OneOrMore"), ("〇*a", "ZeroOrMore")):
        node = _inner(got[src])
        assert node["t"] == f"ub-Challenge{t}"
        assert node["children"][0]["pattern"] == "a"
    space = _inner(got["〴s"])
    assert (space["charClass"], space["negated"]) == ("SPACE", False)
    digit = _inner(got["〴D"])
    assert (digit["charClass"], digit["negated"]) == ("DIGIT", True)


def test_repetition_records_counts_and_minimum(probe):
    node = _inner(probe("〇{2;4-5;7+}a")["〇{2;4-5;7+}a"])
    assert node["t"] == "ub-ChallengeRepetition"
    assert node["counts"] == [2, 4, 5]
    assert node["min"] == 7
    exact = _inner(probe("〇{3}a")["〇{3}a"])
    assert (exact["counts"], exact["min"]) == ([3], None)


def test_charset_alternative_and_named_nodes(probe):
    src = "【a┇「〤b〜dx」┇「〴w」】"
    alt = _inner(probe(src)[src])
    assert alt["t"] == "ub-ChallengeAlternative"
    assert len(alt["children"]) == 3
    plain, ranged, classes = (_first_leaf(c) for c in alt["children"])
    assert plain["pattern"] == "a"
    assert (ranged["t"], ranged["negated"], ranged["chars"]) == (
        "ub-ChallengeCharSet",
        True,
        "bcdx",
    )
    assert (classes["classes"], classes["negated"], classes["chars"]) == (["WORD"], False, "")
    named = _inner(probe("〶$N=a")["〶$N=a"])
    assert (named["t"], named["name"]) == ("ub-CompositeNamed", "N")


def test_upto_and_lazy_nodes(probe):
    up = probe("〄>b")["〄>b"]
    assert [c["t"] for c in up["children"]] == ["ub-ChallengeUpTo", "ub-ChallengeSingleChar"]
    old = probe("〄+ a -> b")["〄+ a -> b"]
    assert old["children"][0]["t"] == "ub-ChallengeOneOrMoreUpToOldVersion"
    assert len(old["children"][0]["children"]) == 2


def test_gantt_subjects_match_factory_registry(gantt):
    src = _git_show(FACTORY_PATH)
    expected = re.findall(r"new NaturalGanttCommand\((Subject\w+)\.ME\)", src)
    assert len(expected) == 9
    assert [s["class"] for s in gantt["subjects"]] == [f"{LANG_PACKAGE}{n}" for n in expected]
    orders = [s["commandOrder"] for s in gantt["subjects"]]
    assert orders == list(range(orders[0], orders[0] + 9))
    assert all(s["tree"]["t"].startswith("ub-") for s in gantt["subjects"])


def test_gantt_verb_phrase_counts_match_source(gantt):
    for subject in gantt["subjects"]:
        simple = subject["class"].rsplit(".", 1)[1]
        src = _git_show(f"{LANG_DIR}/{simple}.java")
        live = re.findall(r"^\s*result\.add\(new VerbPhraseAction\(", src, re.MULTILINE)
        assert len(subject["verbPhrases"]) == len(live), simple
        assert [p["order"] for p in subject["verbPhrases"]] == list(range(len(live)))


def test_gantt_verbs_match_verbs_class(gantt):
    names = re.findall(r"public static Verbs (\w+) =", _git_show(VERBS_PATH))
    assert len(names) == 20
    assert [v["name"] for v in gantt["verbs"]] == names
    is_or_are = next(v for v in gantt["verbs"] if v["name"] == "isOrAre")
    alt = _inner(is_or_are["tree"])
    assert alt["t"] == "ub-ChallengeAlternative"
    assert len(alt["children"]) == 2
    phrase_verbs = {p["verb"] for s in gantt["subjects"] for p in s["verbPhrases"]}
    assert phrase_verbs <= set(names)


def test_gantt_complements_cover_every_complement_class(gantt):
    listing = subprocess.run(
        ["git", "-C", str(require("src")), "ls-tree", "--name-only", PIN_SHA, f"{LANG_DIR}/"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    files = {Path(p).stem for p in listing if Path(p).name.startswith("Complement")}
    seen: set[str] = set()

    def collect(entry):
        seen.add(entry["class"].rsplit(".", 1)[1])
        for part in entry.get("parts", []):
            collect(part)

    for entry in gantt["complements"]:
        collect(entry)
        assert entry["tree"]["t"].startswith("ub-")
    assert files <= seen
    assert len(files) >= 20
    pair = next(c for c in gantt["complements"] if c["class"].endswith(".PairOfSomething"))
    assert [p["class"].rsplit(".", 1)[1] for p in pair["parts"]] == [
        "ComplementBeforeOrAfterOrAtTaskStartOrEnd",
        "ComplementWithColorLink",
    ]


def test_gantt_complement_params_distinguish_variants(gantt):
    dates = [c for c in gantt["complements"] if c["class"].endswith(".ComplementDate")]
    assert {c["params"]["type"] for c in dates} == {"ANY", "ONLY_RELATIVE", "ONLY_ABSOLUTE"}


def test_gantt_phrases_reference_complements_by_index(gantt):
    task = next(s for s in gantt["subjects"] if s["class"].endswith(".SubjectTask"))
    for phrase in task["verbPhrases"]:
        target = gantt["complements"][phrase["complement"]]
        assert target["class"] == phrase["complementClass"]
    first = task["verbPhrases"][0]
    assert (first["verb"], first["complementClass"].rsplit(".", 1)[1]) == (
        "requires",
        "ComplementDuration",
    )
    assert first["ignored"]["t"].startswith("ub-")
    starts_no_ignored = [p for p in task["verbPhrases"] if p["ignored"] is None]
    assert starts_no_ignored


def test_gantt_combination_describes_sentence_formation(gantt):
    combination = gantt["combination"]
    assert "VERBPHRASE" in combination["rule"]
    assert combination["spaces"]["t"] == "ub-CompositeList"
    assert combination["and"]["t"] == "ub-CompositeList"
    assert any("NaturalGanttCommand.java:61" in c for c in combination["cites"])
    assert gantt["pin"]["sha"] == PIN_SHA


def test_generated_gantt_lang_in_repo_is_current(gantt):
    committed = build.REPO_ROOT / "extracted" / "gantt-lang.json"
    assert json.loads(committed.read_text(encoding="utf-8")) == gantt
