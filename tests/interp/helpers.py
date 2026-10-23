"""Test helpers for the interpreter tests."""

from __future__ import annotations

from tools.interp import Verdict

PATHOLOGICAL_PATTERN = "^(a|aa)+$"
PATHOLOGICAL_INPUT = "a" * 60 + "!"


def uml(*lines: str) -> str:
    """A ``@startuml`` block around ``lines``."""
    return "\n".join(["@startuml", *lines, "@enduml"])


def failure_of(verdict: Verdict) -> tuple[int, str]:
    """``(line, text)`` of a verdict's first failure."""
    failure = verdict["first_failure"]
    assert failure is not None
    return failure["line"], failure["text"]
