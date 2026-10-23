"""Tests for tools.interp.source."""

from __future__ import annotations

import pytest

from tools.interp.source import (
    Line,
    embedded_type,
    is_end_directive,
    is_start_directive,
    split_block,
    split_blocks,
    start_keyword,
    strip_comments,
    trin,
)


def lines(*texts: str) -> list[Line]:
    return [Line(n, t, trin(t)) for n, t in enumerate(texts, start=1)]


def texts(kept: list[Line]) -> list[str]:
    return [ln.text for ln in kept]


def test_trin_strips_control_chars_and_spaces_only() -> None:
    assert trin("\t \x01 a b \r") == "a b"
    assert trin(" a ") == " a "


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("@startuml", True),
        ("  \\startuml", True),
        ("@start", False),
        ("@startx", True),
        ("start uml", False),
        ("   ", False),
        ("@end", False),
    ],
)
def test_is_start_directive(text: str, expected: bool) -> None:
    assert is_start_directive(text) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [("@enduml", True), (" \\end", True), ("@start", False), ("end", False), ("", False)],
)
def test_is_end_directive(text: str, expected: bool) -> None:
    assert is_end_directive(text) is expected


def test_start_keyword() -> None:
    assert start_keyword("@startMindmap") == "mindmap"
    assert start_keyword("@startuml name=a") == "uml"
    assert start_keyword("@startuml{x}") == "uml"
    assert start_keyword("plain") == ""


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("{{", "uml"),
        ("  {{  ", "uml"),
        ("{{json", "json"),
        ("{{ json", None),
        ("{{ nonsense", None),
        ("{{salt  ", "salt"),
        ("x {{", None),
    ],
)
def test_embedded_type(text: str, expected: str | None) -> None:
    assert embedded_type(text) == expected


def test_strip_comments_mirrors_read_filter() -> None:
    src = lines(
        "keep1",
        "  ' line comment",
        "/' inline '/",
        "/' start",
        "inside",
        "end '/",
        "keep2",
        "/' x '/ trailing",
        "keep3",
    )
    # "/' x '/ trailing" starts with /' but neither ends with '/ nor lacks '/ -> kept.
    assert texts(strip_comments(src)) == ["keep1", "keep2", "/' x '/ trailing", "keep3"]


def test_strip_comments_unclosed_long_comment_drops_rest() -> None:
    assert texts(strip_comments(lines("a", "/' open", "b", "c"))) == ["a"]


def test_split_block_numbers_lines_and_stops_at_end() -> None:
    block = split_block("\n@startuml\nA\n\n@enduml\nB")
    assert block.start == Line(2, "@startuml", "@startuml")
    assert block.keyword == "uml"
    assert [(ln.number, ln.text) for ln in block.body] == [(3, "A"), (4, "")]


def test_split_block_without_start_is_all_body() -> None:
    block = split_block("A\r\nB")
    assert block.start is None
    assert block.keyword is None
    assert [ln.text for ln in block.body] == ["A", "B"]


def test_split_block_empty_text() -> None:
    block = split_block("")
    assert block.start is None
    assert [ln.number for ln in block.body] == [1]


def test_split_blocks_mirrors_block_uml_builder() -> None:
    text = "intro text\n@startuml\nA\n@startuml\nB\n@enduml\nbetween\n\\startdot x\nC\n\\enddot\n"
    assert split_blocks(text) == ["@startuml\nB\n@enduml", "\\startdot x\nC\n\\enddot"]


def test_split_blocks_drops_unterminated_and_non_directives() -> None:
    assert split_blocks("@startuml\nA\n") == []
    assert split_blocks("@STARTUML\nA\n@ENDUML") == []
    assert split_blocks("@start\nA\n@end") == []
    assert split_blocks("@enduml\n@startmindmap\r\n* a\r\n@endwbs\r\n") == [
        "@startmindmap\n* a\n@endwbs"
    ]


def test_split_block_records_the_end_line() -> None:
    block = split_block("@startuml\nA\n@endmindmap\nrest")
    assert block.end is not None
    assert (block.end.number, block.end.text) == (3, "@endmindmap")
    assert split_block("@startuml\nA").end is None
