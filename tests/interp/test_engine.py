"""Tests for tools.interp.engine against toy YAML models (no jar needed)."""

from __future__ import annotations

import time

from tools.interp import accepts
from tools.interp.engine import Interpreter
from tools.model import ResolvedModel, ResolvedModels

from .helpers import PATHOLOGICAL_INPUT, PATHOLOGICAL_PATTERN, failure_of, uml


def test_verdict_has_exactly_the_i3_keys(models: ResolvedModels) -> None:
    verdict = accepts(models, uml("alpha x"))
    assert verdict == {
        "accepted": True,
        "diagram": "SEQUENCE",
        "first_failure": None,
        "model": "seqtoy",
        "status": "ok",
    }


def test_block_matching_only_second_diagram_is_accepted_by_it(models: ResolvedModels) -> None:
    verdict = accepts(models, uml("beta x", "beta y"))
    assert (verdict["accepted"], verdict["diagram"], verdict["status"]) == (True, "CLASS", "ok")


def test_earlier_diagram_wins_when_both_accept(models: ResolvedModels) -> None:
    verdict = accepts(models, uml("title hello"))
    assert verdict["model"] == "seqtoy"


def test_start_map_order_overrides_default_order(models: ResolvedModels) -> None:
    verdict = accepts(models, uml("title hi"), start_map={"uml": ["classtoy", "seqtoy"]})
    assert verdict["model"] == "classtoy"
    prefixed = accepts(models, uml("title hi"), start_map={"@startuml": ["classtoy"]})
    assert prefixed["model"] == "classtoy"


def test_start_map_without_keyword_is_unsupported_not_an_error(models: ResolvedModels) -> None:
    # PSystemUnsupported is not a PSystemError (PSystemBuilder.java:283-284): accepted.
    verdict = accepts(models, uml("alpha x"), start_map={"salt": ["seqtoy"]})
    assert verdict == {
        "accepted": True,
        "diagram": None,
        "first_failure": None,
        "model": None,
        "status": "ok",
    }


def test_start_map_with_known_keyword_but_no_models_rejects(models: ResolvedModels) -> None:
    verdict = accepts(models, uml("alpha x"), start_map={"uml": ["ghost"]})
    assert (verdict["accepted"], verdict["status"]) == (False, "reject")
    assert failure_of(verdict) == (1, "@startuml")


def test_multiline_consumed_until_end_then_next_line_dispatched(models: ResolvedModels) -> None:
    text = uml("note", "anything goes", "alpha ignored by class", "end note", "beta z")
    verdict = accepts(models, text)
    assert (verdict["accepted"], verdict["model"]) == (True, "classtoy")


def test_line_after_multiline_end_is_dispatched_normally_and_can_fail(
    models: ResolvedModels,
) -> None:
    verdict = accepts(models, uml("note", "body", "end note", "nonsense here"))
    assert verdict["accepted"] is False
    assert failure_of(verdict) == (5, "nonsense here")


def test_unterminated_multiline_is_dropped_and_next_command_tried(models: ResolvedModels) -> None:
    verdict = accepts(models, uml("note", "beta x"))
    # CommandNoteMulti never closes -> skipped; CommandNoteSingle takes "note".
    assert (verdict["accepted"], verdict["model"]) == (True, "classtoy")


def test_embedded_diagram_end_does_not_close_outer_multiline(models: ResolvedModels) -> None:
    text = uml("note", "{{", "end note", "}}", "end note", "beta q")
    assert accepts(models, text)["accepted"] is True
    # Without the closing "}}" the embedded group swallows the rest -> the multiline
    # never closes, CommandNoteSingle takes "note" and "{{" is then unmatched.
    broken = uml("note", "{{", "end note", "end note", "beta q")
    assert failure_of(accepts(models, broken)) == (3, "{{")


def test_no_matching_command_reports_one_based_line_and_text(models: ResolvedModels) -> None:
    text = "\n@startuml\nalpha ok\n  bogus line  \n@enduml"
    verdict = accepts(models, text)
    assert verdict == {
        "accepted": False,
        "diagram": None,
        "first_failure": {"line": 4, "text": "  bogus line  "},
        "model": None,
        "status": "reject",
    }


def test_both_commands_match_earlier_one_wins_by_push_effect(models: ResolvedModels) -> None:
    # CommandFirst (push ctx_one) precedes CommandSecond (push ctx_two) in context order.
    assert accepts(models, uml("dup", "one"))["accepted"] is True
    second = accepts(models, uml("dup", "two"))
    assert failure_of(second) == (3, "two")


def test_pop_returns_to_main_and_push_enters_body(models: ResolvedModels) -> None:
    assert accepts(models, uml("open {", "member a", "member b", "}", "beta c"))["accepted"]
    outside = accepts(models, uml("member a"))
    assert failure_of(outside) == (2, "member a")
    inside = accepts(models, uml("open {", "beta c"))
    assert failure_of(inside) == (3, "beta c")


def test_set_replaces_top_of_stack(models: ResolvedModels) -> None:
    assert accepts(models, uml("swap", "two"))["accepted"] is True
    assert failure_of(accepts(models, uml("swap", "one"))) == (3, "one")
    # set replaced main (no push), so the pop in ctx_two was a no-op: still in ctx_two.
    assert failure_of(accepts(models, uml("swap", "two", "beta x"))) == (4, "beta x")


def test_pop_on_bottom_context_is_a_noop(models: ResolvedModels) -> None:
    # "}" is only valid inside body; at main it is rejected, never underflows.
    assert failure_of(accepts(models, uml("}"))) == (2, "}")


def test_bracket_command_balances_nested_braces(models: ResolvedModels) -> None:
    ok = uml("package a {", "inner {", "}", "}", "beta x")
    assert accepts(models, ok)["accepted"] is True
    unbalanced = accepts(models, uml("package a {", "inner {", "}", "beta x"))
    assert unbalanced["accepted"] is False
    assert failure_of(unbalanced) == (2, "package a {")


def test_bracket_command_negative_depth_is_dropped(models: ResolvedModels) -> None:
    verdict = accepts(models, uml("package a {", "}", "}"))
    assert failure_of(verdict) == (4, "}")


def test_opaque_swallows_rest_of_block_up_to_end(models: ResolvedModels) -> None:
    text = "@startdot\ndigraph g {\n a -> b ; ((( not parsed\n}\n@enddot"
    verdict = accepts(models, text)
    assert (verdict["accepted"], verdict["model"]) == (True, "dottoy")
    assert failure_of(accepts(models, "@startdot\nnot digraph\n@enddot")) == (2, "not digraph")


def test_comments_blank_lines_and_text_after_end_are_ignored(models: ResolvedModels) -> None:
    text = "\n".join(
        [
            "@startuml",
            "' a line comment",
            "",
            "/' one liner '/",
            "/' multi",
            "this is not a command",
            "'/",
            "alpha x",
            "@enduml",
            "garbage after end",
        ]
    )
    assert accepts(models, text)["accepted"] is True


def test_empty_body_is_rejected_at_the_start_line(models: ResolvedModels) -> None:
    verdict = accepts(models, "\n@startuml\n' only a comment\n\n@enduml")
    assert (verdict["accepted"], verdict["status"]) == (False, "reject")
    assert failure_of(verdict) == (2, "@startuml")


def test_bare_body_without_start_line_tries_every_diagram(models: ResolvedModels) -> None:
    assert accepts(models, "beta x")["model"] == "classtoy"
    assert failure_of(accepts(models, "alpha x\nzzz")) == (2, "zzz")


def test_unknown_start_keyword_is_unsupported_and_accepted(models: ResolvedModels) -> None:
    # PSystemErrorUtils.checkBasicError returns PSystemUnsupported (:58-59), not an error.
    verdict = accepts(models, "@startnope\nalpha x\n@endnope")
    assert (verdict["accepted"], verdict["status"], verdict["diagram"]) == (True, "ok", None)


def test_reported_failure_is_the_one_that_got_furthest(models: ResolvedModels) -> None:
    # seqtoy dies at line 3 ("beta"), classtoy at line 2 ("alpha") -> seqtoy's wins.
    verdict = accepts(models, uml("alpha x", "beta y"))
    assert failure_of(verdict) == (3, "beta y")
    # classtoy gets further here (line 4), seqtoy fails at 2.
    verdict = accepts(models, uml("beta x", "beta y", "alpha z"))
    assert failure_of(verdict) == (4, "alpha z")


def test_crlf_and_indentation_are_trimmed(models: ResolvedModels) -> None:
    assert accepts(models, "@startuml\r\n\talpha x  \r\n@enduml\r\n")["accepted"] is True


def test_pathological_regex_times_out_promptly() -> None:
    models = _single_rule_models({"regex": PATHOLOGICAL_PATTERN})
    started = time.monotonic()
    verdict = accepts(models, uml(PATHOLOGICAL_INPUT), timeout_s=0.1)
    assert time.monotonic() - started < 3.0
    assert verdict == {
        "accepted": False,
        "diagram": None,
        "first_failure": None,
        "model": None,
        "status": "timeout",
    }


def test_spent_budget_between_regex_calls_times_out() -> None:
    models = _single_rule_models({"regex": "x"})
    ticks = iter([0.0, 5.0, 5.0, 5.0, 5.0, 5.0])
    verdict = Interpreter(models, clock=lambda: next(ticks)).accepts(uml("x"), timeout_s=1.0)
    assert verdict["status"] == "timeout"


def test_uncompilable_model_regex_gives_error_status() -> None:
    models = _single_rule_models({"regex": "("})
    verdict = accepts(models, uml("x"))
    assert (verdict["accepted"], verdict["status"], verdict["first_failure"]) == (
        False,
        "error",
        None,
    )


def test_unsupported_java_syntax_gives_error_status() -> None:
    verdict = accepts(_single_rule_models({"regex": "[a[b]]"}), uml("x"))
    assert (verdict["accepted"], verdict["status"]) == (False, "error")


def test_unresolved_ref_and_missing_context_give_error_status() -> None:
    assert accepts(_single_rule_models({"ref": "NOPE"}), uml("x"))["status"] == "error"
    models = _single_rule_models({"regex": "x"}, push="ghost")
    assert accepts(models, uml("x", "y"))["status"] == "error"


def test_interpreter_cache_follows_models_identity(models: ResolvedModels) -> None:
    assert accepts(models, uml("alpha x"))["model"] == "seqtoy"
    other = _single_rule_models({"regex": "x"})
    assert accepts(other, uml("x"))["model"] == "only"
    assert accepts(models, uml("alpha x"))["model"] == "seqtoy"


def _single_rule_models(parts: dict[str, str], push: str | None = None) -> ResolvedModels:
    entry: dict[str, object] = {
        "command": "CommandOnly",
        "provenance": {"class": "toy.Only"},
        "kind": "single",
        "parts": parts,
    }
    if push:
        entry["push"] = push
    model = ResolvedModel(
        id="only",
        layer="diagram",
        path=None,
        diagram="SEQUENCE",
        variables={},
        contexts={"main": [entry]},
    )
    return {"only": model}


def test_line_text_keeps_java_line_separators_for_the_regex() -> None:
    # Line.text mirrors ReadLineReader (only BOM, U+2013 and breaks change); trin keeps
    # U+0085/U+2028/U+2029, which Java's `.` refuses but its implicit `$` tolerates once.
    models = _single_rule_models({"regex": "title (.*)"})
    assert accepts(models, uml("title a\u2028"))["accepted"] is True
    assert accepts(models, uml("title a\x85"))["accepted"] is True
    rejected = accepts(models, uml("title a\u2028b"))
    assert (rejected["accepted"], failure_of(rejected)) == (False, (2, "title a\u2028b"))
    assert accepts(models, uml("title a\u2029\u2029"))["accepted"] is False
    assert accepts(models, uml("title \u2013"))["accepted"] is True  # U+2013 becomes "-"


def test_join_k_1_is_the_single_line_case(models: ResolvedModels) -> None:
    assert accepts(models, uml("opt", "beta x"))["accepted"] is True


def test_join_smallest_k_wins(models: ResolvedModels) -> None:
    # "opt" matches at k=1, so "z" is dispatched on its own and fails.
    assert failure_of(accepts(models, uml("opt", "z"))) == (3, "z")


def test_join_joins_following_lines_with_private_use_joiner(models: ResolvedModels) -> None:
    assert accepts(models, uml("wrap a", "b", "beta x"))["accepted"] is True
    assert failure_of(accepts(models, uml("wrap a", "b", "c"))) == (4, "c")


def test_join_beyond_max_lines_plus_one_is_dropped(models: ResolvedModels) -> None:
    # CommandWrapFar needs four units but max_lines=2 allows at most three.
    assert failure_of(accepts(models, uml("far", "a", "b", "c"))) == (2, "far")


def test_join_dropped_when_lines_run_out(models: ResolvedModels) -> None:
    assert failure_of(accepts(models, uml("wrap a"))) == (2, "wrap a")


def test_join_unit_is_an_embedded_group(models: ResolvedModels) -> None:
    # Two units joined: "wrap a" + one "{{uml ... }}" group that is not \w+ -> dropped.
    verdict = accepts(models, uml("wrap a", "{{uml", "x", "}}"))
    assert failure_of(verdict) == (2, "wrap a")
