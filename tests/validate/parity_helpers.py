"""Fakes and builders shared by the parity tests."""

from __future__ import annotations

from pathlib import Path

from tools.interp import Verdict
from tools.validate.parity_core import BlockResult
from tools.validate.parity_run import Job, Outcome

TOY_MODEL = """\
schema_version: 1
id: toydiagram
layer: diagram
diagram: CLASS
factory: ToyDiagramFactory
contexts:
  main:
    - command: CommandToyClass
      provenance: {class: toy.CommandToyClass}
      kind: single
      parts: {regex: "class\\\\s+\\\\w+"}
"""
GOOD_BLOCK = "@startuml\nclass A\n@enduml"
BAD_BLOCK = "@startuml\nnonsense here\n@enduml"


def verdict(
    accepted: bool,
    status: str | None = None,
    diagram: str | None = None,
    model: str | None = None,
) -> Verdict:
    """A hand-built I3 verdict."""
    return {
        "accepted": accepted,
        "diagram": diagram,
        "first_failure": None if accepted else {"line": 2, "text": "nonsense"},
        "model": model,
        "status": status or ("ok" if accepted else "reject"),  # type: ignore[typeddict-item]
    }


def result(
    name: str,
    *,
    oracle: bool,
    interp: Verdict,
    raw: Verdict | None = None,
    otype: str | None = "CLASS",
) -> BlockResult:
    """One BlockResult in a fake corpus."""
    return BlockResult(name, 0, oracle, otype, interp, raw)


def job(name: str, text: str, *, oracle: bool, otype: str | None = "CLASS") -> Job:
    """One Job; the raw text equals the L2 text."""
    return Job(name, 0, text, text, oracle, otype)


def write_toy_models(directory: Path) -> Path:
    """Write the one-rule toy model tree and return its directory."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "toydiagram.yaml").write_text(TOY_MODEL, encoding="utf-8")
    return directory


def fixed_outcomes(outcome: Outcome) -> object:
    """An ``InterpFn`` returning the same outcome for every job."""
    return lambda _job: outcome
