from __future__ import annotations

import regex

from tools.interp.scan import JOINER, Deadline, Join, scan_join
from tools.interp.source import Line

UNCAPPED = 100_000


def _body(texts: list[str]) -> list[Line]:
    return [Line(n, t, t.strip()) for n, t in enumerate(texts, 1)]


class CountingDeadline(Deadline):
    def __init__(self) -> None:
        super().__init__(10.0)
        self.calls = 0

    def fullmatch(self, pattern, text):  # type: ignore[no-untyped-def]
        self.calls += 1
        return super().fullmatch(pattern, text)


def test_prefix_reports_whether_text_can_still_extend_to_a_match() -> None:
    pattern = regex.compile("<style>" + JOINER + "a" + JOINER + "</style>")
    deadline = Deadline(10.0)
    assert deadline.prefix(pattern, "<style>" + JOINER) is True
    assert deadline.prefix(pattern, "x" + JOINER) is False


def test_uncapped_join_stops_once_no_extension_can_match() -> None:
    pattern = regex.compile("<style>(?:" + JOINER + "[a-z]+)*" + JOINER + "</style>")
    body = _body(["class A"] + ["line"] * 5000)
    deadline = CountingDeadline()
    assert scan_join(Join(pattern, UNCAPPED), body, 0, deadline) is None
    assert deadline.calls == 1


def test_uncapped_join_still_finds_the_smallest_matching_k() -> None:
    pattern = regex.compile("<style>(?:" + JOINER + "[a-z]+)*" + JOINER + "</style>")
    body = _body(["<style>", "a", "b", "</style>", "after"])
    assert scan_join(Join(pattern, UNCAPPED), body, 0, Deadline(10.0)) == 4


def test_prefix_raises_block_timeout_when_budget_is_spent() -> None:
    import pytest

    from tools.interp.scan import BlockTimeout

    ticks = iter([0.0, 5.0])
    deadline = Deadline(1.0, clock=lambda: next(ticks))
    with pytest.raises(BlockTimeout):
        deadline.prefix(regex.compile("a"), "a")


def test_prefix_turns_regex_timeout_into_block_timeout() -> None:
    import pytest

    from tools.interp.scan import BlockTimeout

    class Slow:
        def fullmatch(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise TimeoutError

    with pytest.raises(BlockTimeout):
        Deadline(10.0).prefix(Slow(), "a")
