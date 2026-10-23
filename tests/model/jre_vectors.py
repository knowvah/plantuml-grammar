"""Reference vectors for ``tools.model.java_regex``: generation, Java runner, comparison.

``build_cases`` makes a deterministic (seeded) set of Java regexes and a pool of test
strings; ``java_verdicts`` asks real ``java.util.regex`` (Java 21, single-file launch of
``tests/fixtures/java_regex/Vectors.java``) for the verdict of every pattern on every
string; ``python_verdicts`` asks the translation. ``vectors.json`` stores the Java answers
so unit tests need no JVM; the corpus-marked test regenerates them and compares.

``python -m tests.model.jre_vectors`` rewrites the fixture.
"""

from __future__ import annotations

import json
import random
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

import regex

from tools.model.java_regex import line_pattern, to_python

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "java_regex"
VECTORS = FIXTURE_DIR / "vectors.json"
JAVA_SOURCE = FIXTURE_DIR / "Vectors.java"
SEED = 20261015
PATTERN_COUNT = 1100
MODE_LINE, MODE_PATTERN = "line", "pattern"
JAVA_ERROR = "E"
MAX_BMP = 0xFFFF
LOOKBEHIND = regex.compile(r"\(\?<[=!]")

# Characters the strings and literal atoms are drawn from: ASCII letters of both cases,
# digits, blanks of every Java flavour, and the non-ASCII characters whose treatment
# differs between Java (ASCII defaults) and Python `regex` (Unicode defaults).
STRING_CHARS = [
    *'abkKsSiIzZ09_ -!.[]\\<>"/$#:~^{}',
    "\t",
    "\x0b",
    "\x0c",
    "\xe9",
    "\xc9",
    "ı",
    "İ",
    "K",
    "ſ",
    "٣",
    "\xa0",
    "\x85",
    " ",
    " ",
    " ",
    "́",
    "α",
    "Α",
    "\U0001f600",
    "\U00010400",
    "\U0001d167",
    "\n",
    "\r",
]
LITERALS = [*"abkKsSiIzZ09_ -", "\xe9", "\xc9", "ı", "İ", "K", "ſ", "\xa0"]
ESCAPES = [
    *("\\d", "\\D", "\\w", "\\W", "\\s", "\\S", "\\b", "\\B", "\\x41", "\\x6b", "\\t"),
    *("\\p{L}", "\\p{Lu}", "\\p{Ll}", "\\P{Lu}", "\\p{N}", "\\p{Nd}", "\\p{Mn}", "\\P{L}"),
    *("\\p{Alpha}", "\\p{Upper}", "\\p{Lower}", "\\P{Alpha}", "\\p{Punct}", "\\p{Space}"),
    *("\\p{Digit}", "\\p{Alnum}", "\\p{XDigit}", "\\p{ASCII}", "\\p{Blank}", "\\p{Cntrl}"),
    *("\\p{Graph}", "\\p{Print}", "\\P{Upper}", "\\P{Digit}", "\\pL", "\\PL"),
]
CLASS_ITEMS = [
    *("a", "k", "K", "z", "0", "_", "-", "\xe9", "K", "\\.", "\\[", "\\]", "\\x41"),
    *("<", ">", '"', "/", "$", "#", ":", "~", "{", "}", "\\^", "\\\\"),
    *("a-f", "A-Z", "Z-a", "0-9", "a-z", "k-t", "A-z", "\xe0-\xef", "\\x30-\\x39"),
    *ESCAPES[:6],
    *("\\p{L}", "\\p{Lu}", "\\p{Alpha}", "\\P{Upper}", "\\p{Punct}", "\\p{Space}", "\\p{Mn}"),
]
QUANTIFIERS = ["?", "*", "+", "{1,2}", "{2}", "??", "*?", "+?", "*+", "?+"]
FLAGS_GROUPS = ["(?i:", "(?-i:"]


@dataclass(frozen=True)
class Case:
    """One pattern with its mode and case flag."""

    pattern: str
    ci: bool
    mode: str


def _class(rng: random.Random) -> str:
    items = "".join(rng.choice(CLASS_ITEMS) for _ in range(rng.randint(1, 4)))
    return "[" + ("^" if rng.random() < 0.3 else "") + items + "]"


def _atom(rng: random.Random, depth: int, groups: list[int]) -> tuple[str, bool]:
    """``(atom text, quantifiable)``; ``groups`` is ``[opened count, *closed numbers]``."""
    roll = rng.random()
    if roll < 0.28:
        return rng.choice(LITERALS), True
    if roll < 0.52:
        text = rng.choice(ESCAPES)
        return text, not text.startswith(("\\b", "\\B"))
    if roll < 0.62:
        return ".", True
    if roll < 0.78:
        return _class(rng), True
    if roll < 0.82 and len(groups) > 1:
        return f"\\{rng.choice(groups[1:])}", True
    if roll < 0.84:
        return rng.choice(["$", "\\Z", "\\z", "^"]), False
    return _group(rng, depth, groups)


def _group(rng: random.Random, depth: int, groups: list[int]) -> tuple[str, bool]:
    if depth <= 0:
        return rng.choice(LITERALS), True
    kind = rng.choice(["(", "(?:", "(?:", "(?=", "(?!", "(?<=", "(?<!", *FLAGS_GROUPS])
    number = groups[0] + 1 if kind == "(" else 0
    groups[0] += kind == "("
    inner = _sequence(rng, depth - 1, groups, bounded=kind.startswith("(?<"))
    if number:
        groups.append(number)  # only closed groups can be referenced
    return f"{kind}{inner})", kind in ("(", "(?:", *FLAGS_GROUPS)


def _sequence(rng: random.Random, depth: int, groups: list[int], bounded: bool) -> str:
    """Concatenation with optional alternation; ``bounded`` forbids open-ended repeats."""
    alternatives = []
    for _ in range(rng.choice([1, 1, 1, 2])):
        parts = []
        for _ in range(rng.randint(1, 3)):
            atom, quantifiable = _atom(rng, depth, groups)
            if quantifiable and rng.random() < 0.3:
                atom += rng.choice(QUANTIFIERS[3:5] if bounded else QUANTIFIERS)
            parts.append(atom)
        alternatives.append("".join(parts))
    return "|".join(alternatives)


def build_cases(seed: int = SEED, count: int = PATTERN_COUNT) -> list[Case]:
    """Deterministic random patterns; the same seed always yields the same list."""
    rng = random.Random(seed)
    cases = []
    for _ in range(count):
        pattern = _sequence(rng, 2, [0], bounded=False)
        cases.append(Case(pattern, rng.random() < 0.5, rng.choice([MODE_LINE, MODE_PATTERN])))
    return cases


def build_strings(seed: int = SEED) -> list[str]:
    """The shared string pool: every single char, random pairs/triples, hand-picked."""
    rng = random.Random(seed + 1)
    pool = ["", *STRING_CHARS]
    pool += ["".join(rng.choices(STRING_CHARS, k=2)) for _ in range(110)]
    pool += ["".join(rng.choices(STRING_CHARS, k=3)) for _ in range(60)]
    pool += ["ab", "Ab", "a ", "á", "áb", "\xe9́", "a\xe9", "kK", "a b"]
    pool += ["ab ", "ab\x85", "a b", "a ", "a\r\n", "  ", "1́"]
    return list(dict.fromkeys(pool))


def _hex(text: str) -> str:
    return ".".join(f"{ord(c):x}" for c in text) or "-"


def java_input(cases: list[Case], strings: list[str]) -> str:
    """The TSV Vectors.java reads."""
    joined = ",".join(_hex(s) for s in strings)
    flag = {True: "i", False: "-"}
    rows = [f"{c.mode}\t{flag[c.ci]}\t{_hex(c.pattern)}\t{joined}" for c in cases]
    return "\n".join(rows) + "\n"


def java_verdicts(cases: list[Case], strings: list[str]) -> list[str]:
    """Run real Java; one 0/1 string per case, or ``E`` for a pattern Java rejects."""
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "cases.tsv"
        source.write_text(java_input(cases, strings), encoding="utf-8")
        done = subprocess.run(  # noqa: S603 - fixed argv, trusted local file
            ["java", str(JAVA_SOURCE), str(source)],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            timeout=300,
        )
    return done.stdout.splitlines()


def comparable(case: Case, text: str) -> bool:
    """Is Java's verdict for ``text`` comparable with a code-point engine?

    Java lookbehind steps back in UTF-16 units and may start inside a surrogate pair,
    so a supplementary character next to a lookbehind has no code-point equivalent.
    """
    return not (LOOKBEHIND.search(case.pattern) and any(ord(c) > MAX_BMP for c in text))


def python_verdicts(case: Case, strings: list[str]) -> str:
    """The translation's 0/1 string for one case."""
    source = to_python(case.pattern, ci=case.ci)
    if case.mode == MODE_LINE:
        source = line_pattern(source)
    compiled = regex.compile(source)
    return "".join("1" if compiled.fullmatch(s) else "0" for s in strings)


def dump(cases: list[Case], strings: list[str], verdicts: list[str]) -> str:
    """Fixture JSON: strings once, then ``[pattern, ci, mode, verdicts]`` per valid case."""
    rows = [
        [c.pattern, c.ci, c.mode, v]
        for c, v in zip(cases, verdicts, strict=True)
        if v != JAVA_ERROR
    ]
    return json.dumps({"strings": strings, "cases": rows}, ensure_ascii=True, indent=0) + "\n"


def load() -> tuple[list[Case], list[str], list[str]]:
    """``(cases, strings, java verdicts)`` from the committed fixture."""
    data = json.loads(VECTORS.read_text(encoding="utf-8"))
    cases = [Case(p, ci, mode) for p, ci, mode, _ in data["cases"]]
    return cases, data["strings"], [v for *_, v in data["cases"]]


def main() -> None:
    """Regenerate ``vectors.json`` from real Java."""
    cases, strings = build_cases(), build_strings()
    VECTORS.write_text(dump(cases, strings, java_verdicts(cases, strings)), encoding="utf-8")


if __name__ == "__main__":
    main()
