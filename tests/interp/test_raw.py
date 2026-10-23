"""Raw mode (``raw=True``): the preproc-layer model filters lines before dispatch."""

from __future__ import annotations

from tools.interp import accepts
from tools.model import ResolvedModels

from .helpers import failure_of, uml

PREPROC_ID = "preproctoy"


def test_preproc_lines_are_ignored_unless_raw(models: ResolvedModels) -> None:
    text = uml("!define X 1", "alpha x")
    assert failure_of(accepts(models, text)) == (2, "!define X 1")
    raw = accepts(models, text, raw=True)
    assert (raw["accepted"], raw["model"]) == (True, "seqtoy")


def test_preproc_multiline_consumes_its_body(models: ResolvedModels) -> None:
    text = uml("!procedure p()", "]]] not a command", "!endprocedure", "alpha x")
    assert accepts(models, text, raw=True)["accepted"] is True


def test_preproc_push_set_and_pop_follow_diagram_rule_semantics(models: ResolvedModels) -> None:
    text = uml("!if A", "alpha a", "!else", "alpha b", "!endif", "alpha c")
    assert accepts(models, text, raw=True)["accepted"] is True
    # "!else" exists only in if_body, so at main it reaches the diagram and fails.
    assert failure_of(accepts(models, uml("!else"), raw=True)) == (2, "!else")
    # After "!else" the context was replaced by else_body: a second "!else" is not preproc.
    twice = accepts(models, uml("!if A", "!else", "!else"), raw=True)
    assert failure_of(twice) == (4, "!else")
    # "!if" is only known at main: a nested one reaches the diagram.
    nested = accepts(models, uml("!if A", "!if B", "!endif"), raw=True)
    assert failure_of(nested) == (3, "!if B")


def test_preproc_stack_starts_at_main_for_every_factory_attempt(
    models: ResolvedModels,
) -> None:
    # seqtoy fails on "beta y" with the preproc stack inside if_body; classtoy must see
    # "!if A" offered to preproc main again, not to its own commands.
    verdict = accepts(models, uml("!if A", "beta y"), raw=True)
    assert (verdict["accepted"], verdict["model"]) == (True, "classtoy")


def test_block_of_only_preproc_lines_is_an_empty_diagram(models: ResolvedModels) -> None:
    verdict = accepts(models, uml("!define X 1"), raw=True)
    assert (verdict["accepted"], verdict["status"]) == (False, "reject")
    assert failure_of(verdict) == (1, "@startuml")


def test_raw_without_a_preproc_model_behaves_like_preprocessed_input(
    models: ResolvedModels,
) -> None:
    without = {k: v for k, v in models.items() if k != PREPROC_ID}
    assert failure_of(accepts(without, uml("!define X 1"), raw=True)) == (2, "!define X 1")
    assert accepts(without, uml("alpha x"), raw=True)["accepted"] is True
