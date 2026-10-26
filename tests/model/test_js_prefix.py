"""Prefix-closure regexes (``tools.model.js_prefix``, decision D4 / contract C4).

Unit tests build tiny Parts and run the patterns in Node. The sweep records the texts the
Python interpreter's ``scan_join`` passes to ``Deadline.prefix`` (with the verdict of
``regex`` partial matching), for every join of the resolved model over every block body of
the fixtures (and, marked ``corpus``, of the corpora), and checks in Node that the prefix
pattern accepts each text Python's partial match accepts (a superset). The texts the
pattern accepts that Python rejects are the over-approximation slack, printed per command.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import pytest
import regex

from tests.helpers.models import repo_resolved
from tests.model.node_regex import Job, run_batch
from tests.model.prefix_sweep import JoinSpec, Sweep, _ChainRecorder, sweep_parallel, sweep_paths
from tools.interp.compile import compile_part, part_key
from tools.interp.factories import NON_COMMAND_FACTORIES
from tools.interp.scan import JOINER
from tools.model import Part, ResolvedModels
from tools.model.java_regex import JavaRegexError
from tools.model.java_regex_js import line_pattern_js
from tools.model.js_prefix import MAX_PATTERN_BYTES, TOP_PATTERN, PrefixError, prefix_pattern
from tools.validate.corpus import enumerate_corpora

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures"
STYLE_JOIN = "CommandStyleMultilinesCSS"
ANY = "[^]*"


def _lit(text: str, ci: bool = False) -> Part:
    return {"literal": text, "ci": ci}


def _rx(source: str, ci: bool = False) -> Part:
    return {"regex": source, "ci": ci}


@dataclass(frozen=True)
class Case:
    """A Part with strings its prefix pattern must accept and must reject."""

    part: Part
    accept: tuple[str, ...]
    reject: tuple[str, ...] = ()


CASES: dict[str, Case] = {
    "literal-ci": Case(
        _lit("<style>", True), ("", "<", "<STY", "<Style>", "<style>\n"), ("x", "<styles")
    ),
    "literal-cs": Case(_lit("ab"), ("", "a", "ab"), ("A", "b", "abc")),
    "seq": Case(
        {"seq": [_lit("ab"), _rx("c+d")]}, ("", "a", "ab", "abccc", "abcd"), ("b", "abx", "abcdx")
    ),
    "alt": Case({"alt": [_lit("ab"), _lit("xy")]}, ("", "a", "x", "xy"), ("b", "ay", "xb")),
    "opt": Case(
        {"seq": [{"opt": _lit("a")}, _lit("bc")]}, ("", "a", "b", "ab", "abc", "bc"), ("c", "ac")
    ),
    "star": Case(
        {"seq": [{"star": _lit("ab")}, _lit("c")]},
        ("", "a", "ab", "aba", "ababc", "c"),
        ("b", "ac", "abb"),
    ),
    "plus": Case(
        {"seq": [{"plus": _rx("[0-9]")}, _lit("x")]}, ("", "1", "123", "12x"), ("x1", "a")
    ),
    "lookahead-past-cut": Case(
        {"seq": [_rx("a(?=xyz)"), _rx("xyzq")]},
        ("", "a", "ax", "axy", "axyz", "axyzq"),
        ("b", "ab"),
    ),
    "lookahead-reaching-the-end": Case(_rx("(?=abc)x"), ("", "a", "ab", "abc", "x"), ("b", "abd")),
    "negative-lookahead-reaching-the-end": Case(_rx("(?!abc)x"), ("", "a", "ab", "x"), ("b",)),
    "negative-lookahead": Case(_rx("a(?!b)c"), ("", "a", "ac"), ("x",)),
    "lookbehind": Case(_rx("(?<=x)a"), ("", "a"), ("b",)),
    "anchors": Case({"seq": [_rx("^a$"), _rx("b")]}, ("", "a", "ab"), ("b",)),
    "word-boundary": Case(
        {"seq": [_rx("\\bfoo\\b"), _rx("bar")]}, ("", "fo", "foo", "foobar"), ("x",)
    ),
    "end-anchor-escapes": Case({"seq": [_rx("a\\Z"), _rx("\\zb")]}, ("a", "ab"), ("b",)),
    "backref": Case(_rx("(a)\\1b"), ("", "a", "aa", "aab", "aXb"), ("b",)),
    "backref-two-digits": Case(_rx("(a)\\10b"), ("a", "aXXb"), ("b",)),
    "named-backref": Case(_rx("(?<n>a)\\k<n>b"), ("a", "aXb"), ("b",)),
    "python-named-backref": Case(_rx("(?P<n>a)(?P=n)b"), ("a", "aXb"), ("b",)),
    "backref-other-subpart": Case(
        {"seq": [_rx("(a)"), _rx("\\1b")]}, ("", "a", "aab", "aXb"), ("b",)
    ),
    "atomic": Case(_rx("(?>a+)b"), ("", "a", "aaa", "aaab"), ("aaabc", "ba")),
    "possessive": Case(_rx("a++ab"), ("", "a", "aa"), ("c", "aab")),
    "possessive-star": Case(_rx("a*+b"), ("", "a", "aab"), ("ba",)),
    "lazy": Case(_rx("a+?b"), ("", "a", "aab"), ("c", "aabb")),
    "counted": Case(_rx("a{2,3}b"), ("", "a", "aa", "aaab"), ("c", "aaabb")),
    "class": Case(_rx("[a-c]+x"), ("", "a", "abcx"), ("d", "xx")),
    "escapes": Case(_rx("\\d\\s\\w\\x41\\u0042\\p{L}\\."), ("", "1", "1 ", "1 aABé."), ("a",)),
    "dot": Case(_rx("a.b"), ("", "a", "axb"), ("axxb", "a\nx")),
    "named-group-plain": Case(_rx("(?<n>ab)c"), ("", "a", "abc"), ("b",)),
    "comment": Case(_rx("a(?#note)b"), ("", "a", "ab"), ("b",)),
    "ci-leaf": Case(_rx("abc", True), ("", "A", "aB", "ABC"), ("x",)),
    "inline-flag": Case(_rx("(?i)ab"), ("", "A", "AB"), ("x",)),
    "inline-flag-scoped": Case(_rx("(?i:a)b"), ("A", "Ab"), ("B", "AB")),
    "alternation-in-leaf": Case(_rx("ab|cd"), ("", "a", "c", "cd"), ("b",)),
    "long-rest-alt": Case(
        {"seq": [{"alt": [_lit("a"), _lit("b")]}, _lit("c" * 100)]},
        ("a", "b", "a" + "c" * 99),
        ("c",),
    ),
    "empty-seq": Case({"seq": []}, ("",), ("a",)),
    "zero-repeat": Case({"seq": [_rx("a{0}"), _lit("b")]}, ("", "b"), ("a",)),
    "repeat-empty": Case({"seq": [_rx("(?=a)*"), _lit("b")]}, ("", "b"), ("c",)),
    "define-recursion": Case(_rx("(?(DEFINE)(?<x>a))(?&x)b"), ("", "zzz"), ()),
    "conditional": Case(_rx("(a)?(?(1)b|c)"), ("", "zzz"), ()),
    "nested-class": Case(_rx("[a[b]]c"), ("", "zzz"), ()),
    "quoted": Case(_rx("\\Qab\\E"), ("", "zzz"), ()),
    "unclosed-group": Case(_rx("(ab"), ("", "zzz"), ()),
    "unbalanced-paren": Case(_rx("ab)"), ("", "zzz"), ()),
    "dangling-quantifier": Case(_rx("*a"), ("", "zzz"), ()),
    "illegal-repetition": Case(_rx("a{x"), ("", "zzz"), ()),
    "trailing-backslash": Case(_rx("a\\"), ("", "zzz"), ()),
    "branch-reset": Case(_rx("(?|a|b)"), ("", "zzz"), ()),
    "unsupported-flag": Case(_rx("(?x)a"), ("", "zzz"), ()),
    "unknown-call": Case(_rx("(?R)"), ("", "zzz"), ()),
    "malformed-group": Case(_rx("(?"), ("", "zzz"), ()),
    "top-in-seq-swallows-rest": Case({"seq": [_rx("(?(DEFINE)a)"), _lit("abc")]}, ("", "q"), ()),
    "top-in-repeat": Case({"seq": [{"star": _rx("(?R)")}, _lit("a")]}, ("", "q"), ()),
}


@pytest.fixture(scope="module")
def case_results() -> dict[str, list[bool]]:
    """Node verdicts for every sample of every case, from a single process."""
    names = list(CASES)
    jobs = [Job(prefix_pattern(CASES[n].part), (*CASES[n].accept, *CASES[n].reject)) for n in names]
    outcomes = run_batch(jobs)
    assert all(o.compiles for o in outcomes)
    return {n: o.matches for n, o in zip(names, outcomes, strict=True)}


@pytest.mark.parametrize("name", sorted(CASES))
def test_prefix_pattern_accepts_prefixes_and_rejects_non_prefixes(
    name: str, case_results: dict[str, list[bool]]
) -> None:
    case = CASES[name]
    verdicts = case_results[name]
    accepted = len(case.accept)
    assert verdicts[:accepted] == [True] * accepted
    assert verdicts[accepted:] == [False] * len(case.reject)


def _python_partial(part: Part, text: str) -> bool:
    return compile_part(part).fullmatch(text, partial=True) is not None


@pytest.mark.parametrize("name", sorted(CASES))
def test_prefix_pattern_accepts_whatever_python_partial_match_accepts(
    name: str, case_results: dict[str, list[bool]]
) -> None:
    case = CASES[name]
    samples = (*case.accept, *case.reject)
    try:
        python = [_python_partial(case.part, text) for text in samples]
    except (JavaRegexError, regex.error, MemoryError):  # (?R) exhausts memory in Python
        pytest.skip("the Python translator does not support this leaf")
    assert [js for js, py in zip(case_results[name], python, strict=True) if py] == [True] * sum(
        python
    )


def test_literal_pattern_source_is_the_nested_prefix_chain() -> None:
    assert prefix_pattern(_lit("ab")) == line_pattern_js("(?:|a(?:|b))")


def test_ci_literal_folds_each_letter() -> None:
    assert prefix_pattern(_lit("a", True)) == line_pattern_js("(?:|[aA])")


def test_unparsable_leaf_is_the_top_of_the_lattice() -> None:
    assert prefix_pattern(_rx("(?(DEFINE)(?<x>a))(?&x)")) == line_pattern_js(ANY)


def test_back_reference_widens_to_anything_not_empty() -> None:
    assert prefix_pattern(_rx("(a)\\1")) == line_pattern_js(f"(?:|a{ANY})")


def test_exact_atomic_group_keeps_its_emulation_with_unique_names() -> None:
    pattern = prefix_pattern({"seq": [_rx("(?>a(?>b)c)"), _rx("(?>d)"), _lit("e")]})
    names = [f"(?<_a{n}>" for n in range(4)]
    assert [pattern.count(name) for name in names] == [1, 1, 1, 1]
    assert "(?<_a4>" not in pattern
    assert "@" not in pattern


def test_widened_atomic_group_is_plain() -> None:
    assert "_a" not in prefix_pattern(_rx("(?>(?!x)a|ab)c"))
    assert "_a" not in prefix_pattern(_rx("(?>a\\1)c"))


def test_possessive_quantifier_keeps_its_emulation_when_exact() -> None:
    assert "(?<_a0>" in prefix_pattern({"seq": [_rx("a++"), _rx("b")]})
    assert "(?<_a0>" not in prefix_pattern({"seq": [_rx("(?:(?!x)a)++"), _rx("b")]})


def test_unknown_part_raises() -> None:
    with pytest.raises(PrefixError, match="unresolved or unknown Part"):
        prefix_pattern({"ref": "X"})


def test_oversized_pattern_falls_back_to_top_and_logs(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("tools.model.js_prefix.MAX_PATTERN_BYTES", 10)
    with caplog.at_level(logging.WARNING, logger="tools.model.js_prefix"):
        pattern = prefix_pattern(_lit("abcdef"), command="BigCommand")
    assert pattern == TOP_PATTERN == "^[^]*$"
    [record] = caplog.records
    assert record.command == "BigCommand"  # type: ignore[attr-defined]
    assert record.limit == 10  # type: ignore[attr-defined]


def test_size_limit_is_64_kib() -> None:
    assert MAX_PATTERN_BYTES == 64 * 1024


# --- the resolved model -----------------------------------------------------------------


@pytest.fixture(scope="module")
def models() -> ResolvedModels:
    return repo_resolved()


def _spec(part: Part, max_lines: int, glue: bool, commands: set[str]) -> JoinSpec:
    names = tuple(sorted(commands))
    return JoinSpec(part, max_lines, glue, names, prefix_pattern(part, ",".join(names)))


def _join_specs(models: ResolvedModels) -> list[JoinSpec]:
    """Every distinct (Part, line cap, gluing) join of the model with its prefix pattern."""
    found: dict[tuple[str, int, bool], tuple[Part, set[str]]] = {}
    for model in models.values():
        glue = model.factory not in NON_COMMAND_FACTORIES
        for entries in model.contexts.values():
            for entry in entries:
                if "join" in entry:
                    key = (part_key(entry["parts"]), entry["join"]["max_lines"], glue)
                    found.setdefault(key, (entry["parts"], set()))[1].add(entry["command"])
    return [
        _spec(part, max_lines, glue, cmds) for (_, max_lines, glue), (part, cmds) in found.items()
    ]


@pytest.fixture(scope="module")
def specs(models: ResolvedModels) -> list[JoinSpec]:
    return _join_specs(models)


def test_style_join_prefix_accepts_its_start_and_rejects_other_text(
    specs: list[JoinSpec],
) -> None:
    [spec] = [s for s in specs if STYLE_JOIN in s.commands][:1]
    [outcome] = run_batch([Job(spec.pattern, ("<style>", "<style>" + JOINER, "x", "x" + JOINER))])
    assert outcome.matches == [True, True, False, False]


def test_every_join_prefix_pattern_compiles_in_node(specs: list[JoinSpec]) -> None:
    outcomes = run_batch([Job(s.pattern) for s in specs])
    assert [s.label for s, o in zip(specs, outcomes, strict=True) if not o.compiles] == []


def test_no_join_prefix_pattern_hits_the_size_fallback(specs: list[JoinSpec]) -> None:
    sizes = sorted(len(s.pattern.encode()) for s in specs)
    print(f"\nprefix pattern bytes: max={sizes[-1]} limit={MAX_PATTERN_BYTES}")
    assert {s.label for s in specs if s.pattern == TOP_PATTERN} == set()


def test_chain_offsets_count_utf16_units_and_follow_each_extension() -> None:
    pattern = compile_part(_lit("x"))
    rec = _ChainRecorder({}, 0)
    rec.prefix(pattern, "x")
    rec.prefix(pattern, "x\U0001f600\ue100")
    assert (rec.offsets, rec.verdicts) == ([1, 4], [True, False])
    with pytest.raises(AssertionError, match="extend each other"):
        rec.prefix(pattern, "y")


# --- the sweep: Python partial matching vs the Node pattern -------------------------------


def _report(name: str, sweep: Sweep) -> None:
    print(
        f"\n[{name}] bodies={sweep.bodies} chains={sweep.chains} texts={sweep.texts} "
        f"timeouts={sweep.timeouts} threw={sum(sweep.threw.values())} "
        f"violations={len(sweep.violations)}"
    )
    for label, count in sorted(sweep.threw.items()):
        print(f"  threw {count:>6} {label}")
    for label, slack in sorted(sweep.slack.items()):
        print(f"  slack {slack:>6} (python accepts {sweep.accepted_by_python[label]:>6}) {label}")


def test_prefix_pattern_is_a_superset_of_partial_match_on_fixture_blocks(
    specs: list[JoinSpec],
) -> None:
    sweep = sweep_paths(specs, sorted(FIXTURES.rglob("*.puml")))
    _report("fixtures", sweep)
    assert sweep.bodies > 1000
    assert sweep.violations[:5] == []
    assert sum(sweep.accepted_by_python.values()) > 0


@pytest.mark.corpus
def test_prefix_pattern_is_a_superset_of_partial_match_on_corpus_blocks(
    specs: list[JoinSpec],
) -> None:
    paths = [path for _, path, _ in enumerate_corpora()]
    sweep = sweep_parallel("corpus", specs, paths)
    _report("corpus", sweep)
    assert sweep.violations[:5] == []
