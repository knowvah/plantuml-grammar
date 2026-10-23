"""Ordered line-matching interpreter for the command model (contract I3).

``accepts(models, block_text)`` answers the question the parity harness asks of the
model: would upstream PlantUML accept this (preprocessed) ``@start...@end`` block?
See ``tools.interp.engine`` for the upstream semantics being mirrored and the known
semantic gaps.
"""

from __future__ import annotations

from typing import Literal, TypedDict

STATUS_OK = "ok"
STATUS_REJECT = "reject"
STATUS_TIMEOUT = "timeout"
STATUS_ERROR = "error"

Status = Literal["ok", "reject", "timeout", "error"]


class FirstFailure(TypedDict):
    """The first line no command of the reported diagram accepted."""

    line: int  # 1-based within the block text
    text: str


class Verdict(TypedDict):
    """Contract I3. ``diagram`` is the upstream ``DiagramType`` name of the accepting
    model (compare with the oracle's ``diagram_type``); ``model`` (additive) is its id.
    Both are ``None`` unless a model accepted the block."""

    accepted: bool
    diagram: str | None
    first_failure: FirstFailure | None
    model: str | None
    status: Status


from tools.interp.engine import accepts  # noqa: E402  (engine imports the types above)

__all__ = ["FirstFailure", "Verdict", "accepts"]
