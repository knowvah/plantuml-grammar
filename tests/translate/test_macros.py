import pytest

from tools.translate.macros import (
    convert_quotes,
    expand,
    portability_issues,
    portable,
)

# (macro, Java replacement, Pattern2.java line)
MACRO_TABLE = [
    ("%pLN", "\\p{L}\\p{N}", 56),
    ("%s", "\\s\u00a0", 57),
    ("%q", "'\u2018\u2019", 58),
    ("%g", '"\u201c\u201d\ue121', 59),
]


@pytest.mark.parametrize(("macro", "replacement", "line"), MACRO_TABLE)
def test_macro_matches_pattern2(macro: str, replacement: str, line: int) -> None:
    assert expand(f"a{macro}b") == f"a{replacement}b", f"Pattern2.java:{line}"


def test_expand_leaves_unknown_and_expands_all() -> None:
    assert expand("[%s]+%x%s") == "[\\s\u00a0]+%x\\s\u00a0"


def test_convert_quotes_escapes_metacharacters_only() -> None:
    assert convert_quotes("\\Q<|:\\E|\\Q0)\\E") == "<\\|:|0\\)"


def test_convert_quotes_unterminated_runs_to_end() -> None:
    assert convert_quotes("a\\Qb.c") == "ab\\.c"


def test_portable_expands_then_converts() -> None:
    assert portable("%s\\Q*\\E") == "\\s\u00a0\\*"


@pytest.mark.parametrize(
    ("pattern", "issue"),
    [
        ("a++", "possessive-quantifier"),
        ("[a&&[^b]]", "class-intersection"),
        ("\\Qx\\E", "quote-escape"),
        ("\\h", "horizontal-space-escape"),
        ("(?i)x", "inline-flag"),
        ("(", "uncompilable"),
    ],
)
def test_portability_issues_flags(pattern: str, issue: str) -> None:
    assert issue in portability_issues(pattern)


@pytest.mark.parametrize("pattern", ["\\++", "[a+]+", "(a+)+", "\\p{L}+"])
def test_portability_issues_clean(pattern: str) -> None:
    assert portability_issues(pattern) == []
