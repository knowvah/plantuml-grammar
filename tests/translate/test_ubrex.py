"""UBrex Challenge tree translation (T07)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pcre2
import pytest
import regex

from tools.translate import ubrex
from tools.translate.ubrex import translate_command
from tools.translate.ubrex_regex import (
    CITATIONS,
    HANDLERS,
    WIDTHS,
    Ctx,
    regex_of,
    tree_ci,
)

Node = dict[str, Any]
ROOT = Path(__file__).resolve().parents[2]
CI = "CASE_INSENSITIVE"
CS = "CASE_SENSITIVE"
ALL_TYPES = (
    "ChallengeSingleChar ChallengeCharClass ChallengeCharSet ChallengeAlternative "
    "ChallengeOptional ChallengeZeroOrMore ChallengeOneOrMore "
    "ChallengeOneOrMoreUpToOldVersion ChallengeLazzyOneOrMore ChallengeUpTo "
    "ChallengeRepetition ChallengeEndOfText ChallengeLookAhead ChallengeLookBehind "
    "CompositeList CompositeNamed"
).split()


def n(kind: str, *children: Node, name: str | None = None, **extra: Any) -> Node:
    return {
        "t": f"ub-{kind}",
        "name": name,
        "pattern": None,
        "children": list(children),
        **extra,
    }


def ch(c: str, mode: str = CI) -> Node:
    return n("ChallengeSingleChar", pattern=c, caseMode=mode)


def word(text: str, mode: str = CI) -> Node:
    return n("CompositeList", *(ch(c, mode) for c in text))


def cls(name: str, negated: bool = False) -> Node:
    return n("ChallengeCharClass", charClass=name, negated=negated)


def cset(chars: str, classes: tuple[str, ...] = (), negated: bool = False) -> Node:
    return n("ChallengeCharSet", chars=chars, classes=list(classes), negated=negated, caseMode=CI)


def command(start: Node, end: Node | None = None, kind: str = "single") -> dict[str, Any]:
    return {
        "order": 0,
        "class": "p.UBrexCommandX",
        "kind": kind,
        "engine": "UBrex",
        "start": start,
        "end": end,
        "finalBracket": False,
    }


def rx(node: Node, ci: bool | None = None) -> str:
    return regex_of(node, Ctx(tree_ci(node) if ci is None else ci))


def flatten(part: dict[str, Any]) -> str:
    """Whole-line regex of a Part, with `ci` applied per leaf like the interpreter."""
    for key, joiner in (("seq", ""), ("alt", "|")):
        if key in part:
            return "(?:" + joiner.join(flatten(p) for p in part[key]) + ")"
    for key, quantifier in (("opt", "?"), ("star", "*"), ("plus", "+")):
        if key in part:
            return "(?:" + flatten(part[key]) + ")" + quantifier
    flag = "i" if part.get("ci") else "-i"
    body = part["regex"] if "regex" in part else regex.escape(part["literal"])
    return f"(?{flag}:{body})"


def accepts(part: dict[str, Any], text: str) -> bool:
    return regex.fullmatch(flatten(part), text) is not None


def translated(node: Node) -> dict[str, Any]:
    return translate_command(command(node)).parts


def test_every_type_has_handler_width_and_citation() -> None:
    expected = {f"ub-{t}" for t in ALL_TYPES}
    assert set(HANDLERS) == expected
    assert set(WIDTHS) == expected
    assert set(CITATIONS) == expected
    assert CITATIONS["ub-ChallengeSingleChar"].startswith("ChallengeSingleChar.java:")


# ---- one test per ub-* type -------------------------------------------------------------


def test_single_char_is_ci_literal() -> None:
    assert translated(ch("x")) == {"literal": "x", "ci": True}
    assert translated(ch("x", CS)) == {"literal": "x", "ci": False}


def test_single_char_regex_escapes_meta_and_scopes_case() -> None:
    assert rx(ch(".")) == "\\."
    assert rx(ch("a"), ci=False) == "(?i:a)"
    assert rx(ch("a", CS), ci=True) == "(?-i:a)"
    assert rx(ch("a", CS), ci=False) == "a"


def test_composite_list_merges_literals_and_flattens_nested() -> None:
    node = n("CompositeList", word("if"), n("CompositeList", ch(" "), ch("x")))
    assert translated(node) == {"literal": "if x", "ci": True}


def test_composite_list_keeps_mixed_case_literals_apart() -> None:
    node = n("CompositeList", ch("a"), ch("b", CS))
    assert translated(node) == {
        "seq": [{"literal": "a", "ci": True}, {"literal": "b", "ci": False}]
    }


def test_composite_list_empty_and_regex_form() -> None:
    assert translated(n("CompositeList")) == {"literal": "", "ci": False}
    assert rx(n("CompositeList", ch("a"), cls("DIGIT")), ci=True) == "a[0-9_]"


def test_composite_list_reversed_inside_lookbehind() -> None:
    node = n("ChallengeLookBehind", word("ab"), direction="behind", negated=False)
    assert rx(node) == "(?<=ba)"


def test_alternative_is_alt_of_branches() -> None:
    node = n("ChallengeAlternative", word("on"), word("off"))
    assert translated(node) == {
        "alt": [{"literal": "on", "ci": True}, {"literal": "off", "ci": True}]
    }
    assert rx(node) == "(?:on|off)"
    assert translated(n("ChallengeAlternative", word("on"))) == {"literal": "on", "ci": True}
    assert rx(n("ChallengeAlternative", word("on"))) == "on"


def test_optional_zero_one_or_more_are_unary_parts() -> None:
    assert translated(n("ChallengeOptional", word("ab"))) == {"opt": {"literal": "ab", "ci": True}}
    assert translated(n("ChallengeZeroOrMore", cls("SPACE"))) == {"star": {"regex": "[ ]"}}
    assert translated(n("ChallengeOneOrMore", cls("SPACE"))) == {"plus": {"regex": "[ ]"}}
    assert rx(n("ChallengeOptional", word("ab"))) == "(?:ab)?"
    assert rx(n("ChallengeZeroOrMore", cls("SPACE"))) == "[ ]*"
    assert rx(n("ChallengeOneOrMore", ch("a")), ci=True) == "a+"


@pytest.mark.parametrize(
    ("name", "negated", "expected"),
    [
        ("ANY", False, "[\\s\\S]"),
        ("ANY", True, "[^\\s\\S]"),
        ("SPACE", False, "[ ]"),
        ("SPACE", True, "[^ ]"),
        ("WORD", False, "[a-zA-Z0-9_]"),
        ("DIGIT", False, "[0-9_]"),
        ("GUILLEMET", False, '["“”]'),
        ("ALPHA_NUMERIC", False, "[\\p{L}\\p{Nd}]"),
        ("LETTER", True, "[^\\p{L}]"),
    ],
)
def test_char_class(name: str, negated: bool, expected: str) -> None:
    node = cls(name, negated)
    assert translated(node) == {"regex": expected}
    assert rx(node) == expected


def test_char_set_ranges_escapes_classes_and_negation() -> None:
    assert rx(cset("abc")) == "[a-c]"
    assert rx(cset("[]", negated=True)) == "[^\\[\\]]"
    assert rx(cset("-_", ("ALPHA_NUMERIC",))) == "[\\-_\\p{L}\\p{Nd}]"
    assert rx(cset("\x7f")) == "[\\x7f]"
    assert rx(cset("")) == "(?!)"
    assert rx(cset("", negated=True)) == "[\\s\\S]"
    assert translated(cset("det")) == {"regex": "[det]", "ci": True}


def test_char_set_with_any_class() -> None:
    assert rx(cset("", ("ANY",))) == "[\\s\\S]"
    assert rx(cset("a", ("ANY",), negated=True)) == "[^a\\s\\S]"


def test_repetition_counts_are_exact_runs() -> None:
    node = n("ChallengeRepetition", cls("DIGIT"), min=None, counts=[1, 2, 3, 4])
    assert rx(node) == "(?:[0-9_]){1,4}(?![0-9_])"
    pattern = regex.compile(rx(node))
    assert pattern.fullmatch("1234") and not pattern.fullmatch("12345")
    assert not pattern.fullmatch("")


def test_repetition_split_runs_and_minimum() -> None:
    split = n("ChallengeRepetition", ch("a"), min=None, counts=[2, 4])
    assert rx(split, ci=True) == "(?:(?:a){2}(?!a)|(?:a){4}(?!a))"
    at_least = n("ChallengeRepetition", ch("a"), min=3, counts=[1])
    assert rx(at_least, ci=True) == "(?:(?:a){1}(?!a)|(?:a){3,})"
    assert rx(n("ChallengeRepetition", ch("a"), min=2, counts=[]), ci=True) == "(?:a){2,}"
    assert rx(n("ChallengeRepetition", ch("a"), min=None, counts=[0]), ci=True) == "(?!)"


def test_up_to_consumes_until_the_stop_matches() -> None:
    node = n("ChallengeUpTo", ch("]"))
    assert rx(node) == "(?:(?!\\]).)*(?=\\])".replace(".", "[\\s\\S]")
    assert regex.fullmatch(rx(node) + "\\]", "ab c]")
    assert not regex.fullmatch(rx(node) + "\\]", "ab c")


def test_lazy_and_old_up_to_stop_at_first_stop_without_consuming_it() -> None:
    stop = word("then")
    for kind in ("ChallengeLazzyOneOrMore", "ChallengeOneOrMoreUpToOldVersion"):
        node = n(kind, cls("ANY"), stop)
        assert rx(node) == "[\\s\\S](?:(?!then)[\\s\\S])*(?=then)"
        full = regex.compile(rx(node) + "then", regex.I)
        assert full.fullmatch("x THEN")
        assert not full.fullmatch("then")  # needs at least one origin
        assert not full.fullmatch("a then then")  # stops at the first stop


def test_end_of_text_and_lookahead() -> None:
    assert rx(n("ChallengeEndOfText")) == "$"
    pos = n("ChallengeLookAhead", ch("a"), direction="ahead", negated=False)
    neg = n("ChallengeLookAhead", ch("a"), direction="ahead", negated=True)
    assert rx(pos) == "(?=a)" and rx(neg) == "(?!a)"
    assert translated(pos) == {"regex": "(?=a)", "ci": True}
    assert accepts(
        {"seq": [{"literal": "x", "ci": True}, translated(neg), {"literal": "b", "ci": True}]},
        "xb",
    )


def test_lookbehind_fixed_width_is_preserved() -> None:
    node = n("ChallengeLookBehind", ch("a"), direction="behind", negated=False)
    neg = n("ChallengeLookBehind", ch("a"), direction="behind", negated=True)
    assert rx(node) == "(?<=a)" and rx(neg) == "(?<!a)"
    seq = {"seq": [{"literal": "a", "ci": True}, translated(node), {"literal": "b", "ci": True}]}
    assert accepts(seq, "ab")


def test_variable_width_lookbehind_is_recorded_not_emitted() -> None:
    node = n(
        "ChallengeLookBehind", n("ChallengeOneOrMore", ch("a")), direction="behind", negated=False
    )
    result = translate_command(command(node))
    assert result.parts == {"regex": "", "ci": True}
    assert "portability:variable-width-lookbehind" in result.warnings
    uneven = n(
        "ChallengeLookBehind",
        n("ChallengeAlternative", ch("a"), word("bc")),
        direction="behind",
        negated=True,
    )
    assert "portability:variable-width-lookbehind" in translate_command(command(uneven)).warnings


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        (n("ChallengeOptional", ch("a")), (0, 1)),
        (n("ChallengeZeroOrMore", ch("a")), (0, None)),
        (n("ChallengeRepetition", ch("a"), min=None, counts=[2, 3]), (2, 3)),
        (n("ChallengeRepetition", ch("a"), min=2, counts=[]), (2, None)),
        (n("ChallengeUpTo", ch("a")), (0, None)),
        (n("ChallengeLazzyOneOrMore", ch("a"), ch("b")), (1, None)),
        (n("ChallengeEndOfText"), (0, 0)),
        (n("ChallengeCharSet", chars="a", classes=[], negated=False, caseMode=CI), (1, 1)),
        (n("CompositeNamed", word("ab"), name="N"), (2, 2)),
    ],
)
def test_widths(node: Node, expected: tuple[int, int | None]) -> None:
    assert WIDTHS[node["t"]](node) == expected


# ---- named parts, case, structure --------------------------------------------------------


def test_named_composite_becomes_named_regex_part() -> None:
    node = n("CompositeNamed", n("ChallengeAlternative", word("ab"), word("c")), name="X")
    assert translated(node) == {"regex": "(?:ab|c)", "name": "X", "ci": True}
    assert rx(node) == "(?:ab|c)"


def test_regex_part_case_follows_leaves() -> None:
    assert translated(n("ChallengeUpTo", ch("a"))) == {
        "regex": "(?:(?!a)[\\s\\S])*(?=a)",
        "ci": True,
    }
    assert "ci" not in translated(n("ChallengeUpTo", cls("SPACE")))
    mixed = n("CompositeNamed", n("CompositeList", ch("a"), ch("b", CS)), name="M")
    assert translated(mixed) == {"regex": "a(?-i:b)", "name": "M", "ci": True}
    assert tree_ci(n("CompositeList", ch("a", CS))) is False


def test_unknown_type_is_rejected() -> None:
    with pytest.raises(ValueError, match="ub-Bogus"):
        translate_command(command(n("Bogus")))


def test_trailing_end_of_text_is_implicit() -> None:
    node = n("CompositeList", word("end"), n("ChallengeEndOfText"))
    assert translated(node) == {"literal": "end", "ci": True}
    inner = n("CompositeList", word("a"), n("CompositeList", ch("b"), n("ChallengeEndOfText")))
    assert translated(inner) == {"literal": "ab", "ci": True}
    middle = n("CompositeList", n("ChallengeEndOfText"), ch("a"))
    assert translated(middle)["seq"][0] == {"regex": "$"}


def test_empty_start_after_stripping() -> None:
    assert translated(n("CompositeList", n("ChallengeEndOfText"))) == {
        "literal": "",
        "ci": False,
    }


def test_multiline_translates_end_and_warns_on_committed_match() -> None:
    start = n("CompositeList", word("go"), n("ChallengeOptional", ch("!")))
    result = translate_command(command(start, word("end"), "multiline"))
    assert result.kind == "multiline"
    assert result.end == {"literal": "end", "ci": True}
    assert result.join_max_lines is None
    assert "semantics:committed-match" in result.warnings
    plain = translate_command(command(word("go")))
    assert plain.warnings == ()


def test_final_bracket_is_recorded() -> None:
    cmd = command(word("go"))
    cmd["finalBracket"] = True
    assert "semantics:final-bracket" in translate_command(cmd).warnings


def test_uncompilable_regex_is_flagged() -> None:
    assert ubrex.portability_warnings({"regex": "(?<=a+)b"}) == ()  # regex module accepts it
    assert ubrex.portability_warnings({"regex": "(unclosed"}) == ("portability:uncompilable",)


def test_command_without_start_cannot_be_translated() -> None:
    with pytest.raises(ValueError, match="no UBrex start tree"):
        translate_command({**command(word("a")), "start": None})


# ---- acceptance on the real extracted data ----------------------------------------------


def real_command(factory: str, cls_name: str) -> dict[str, Any]:
    doc = json.loads((ROOT / "extracted" / f"{factory}.json").read_text(encoding="utf-8"))
    return next(c for c in doc["commands"] if c["class"].endswith(cls_name))


def test_ubrex_command_if_accepts_and_rejects() -> None:
    result = translate_command(real_command("ActivityDiagramFactory", ".UBrexCommandIf"))
    assert accepts(result.parts, "if (x) then (yes)")
    assert accepts(result.parts, "IF (x) THEN (yes)")
    # UBrexCommandIf.java:85-87: a bare condition is accepted too (IF2), so `if x then` matches.
    assert accepts(result.parts, "if x then")
    assert not accepts(result.parts, "if")
    assert not accepts(result.parts, "iff (x) then")


def test_all_real_ubrex_commands_compile_in_regex_and_pcre2() -> None:
    count = 0
    warnings: set[str] = set()
    for path in sorted((ROOT / "extracted").glob("*Factory*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for cmd in doc["commands"]:
            if cmd["engine"] != "UBrex" or cmd["start"] is None:
                continue
            result = translate_command(cmd)
            warnings.update(result.warnings)
            for tree in (result.parts, result.end):
                if tree is not None:
                    source = flatten(tree)
                    regex.compile(source)
                    pcre2.compile(source)
                    count += 1
    assert count == 15
    assert warnings <= {"semantics:committed-match"}


def test_real_ubrex_types_all_covered() -> None:
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if str(node.get("t", "")).startswith("ub-"):
                seen.add(node["t"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for path in (ROOT / "extracted").glob("*.json"):
        walk(json.loads(path.read_text(encoding="utf-8")))
    assert seen <= {f"ub-{t}" for t in ALL_TYPES}
    assert seen <= set(HANDLERS)


def test_real_trailing_end_of_text_is_stripped() -> None:
    result = translate_command(real_command("ActivityDiagramFactory", ".UBrexCommandIf"))
    assert "$" not in json.dumps(result.parts)


@pytest.mark.corpus
@pytest.mark.parametrize("node_type", sorted(CITATIONS))
def test_citations_resolve_at_pin(node_type: str) -> None:
    import subprocess

    file, line = CITATIONS[node_type].split(":")
    source = subprocess.run(  # noqa: S603  # nosec B603 - fixed argv
        ["git", "-C", str(Path.home() / "git/plantuml"), "show",
         f"97a5992:src/main/java/com/plantuml/ubrex/{file}"],
        capture_output=True, text=True, check=True,
    ).stdout.splitlines()  # fmt: skip
    assert "runChallenge" in source[int(line) - 1]
