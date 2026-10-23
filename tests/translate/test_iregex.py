from typing import Any

import pytest

from tools.translate.iregex import leaf_to_part, translate_command, translate_node, translate_tree


def leaf(pattern: str, name: str | None = None) -> dict[str, Any]:
    return {"t": "leaf", "name": name, "pattern": pattern, "children": []}


def node(kind: str, *children: dict[str, Any], name: str | None = None) -> dict[str, Any]:
    return {"t": kind, "name": name, "pattern": None, "children": list(children)}


def command(
    start: dict[str, Any],
    end: dict[str, Any] | None = None,
    kind: str = "single",
    cls: str = "p.C",
    **extra: Any,
) -> Any:
    return {"kind": kind, "start": start, "end": end, "class": cls, **extra}


def lit(text: str) -> dict[str, Any]:
    return {"literal": text, "ci": True}


def test_mixed_alternation_leaf() -> None:
    part = leaf_to_part("(interface|enum|abstract[%s]+class)", None)
    assert part == {
        "alt": [lit("interface"), lit("enum"), {"regex": "abstract[\\s\u00a0]+class", "ci": True}]
    }


def test_optional_literal_alternation() -> None:
    assert leaf_to_part("(hide|show)?", None) == {"opt": {"alt": [lit("hide"), lit("show")]}}


def test_star_and_plus_quantifiers() -> None:
    assert leaf_to_part("(?:a|b)*", None) == {"star": {"alt": [lit("a"), lit("b")]}}
    assert leaf_to_part("(a|b)+", None) == {"plus": {"alt": [lit("a"), lit("b")]}}


def test_plain_literal_and_escaped_literal() -> None:
    assert leaf_to_part("footbox", None) == lit("footbox")
    assert leaf_to_part("\\(\\)", None) == lit("()")
    assert leaf_to_part("a|b", None) == {"alt": [lit("a"), lit("b")]}


def test_single_wrapped_literal() -> None:
    assert leaf_to_part("(footbox)", None) == lit("footbox")


def test_named_leaf_stays_regex_with_name() -> None:
    assert leaf_to_part("(a|b)", "TYPE") == {"regex": "(a|b)", "ci": True, "name": "TYPE"}


@pytest.mark.parametrize("pattern", ["[%s]+", "(a)(b)", "(?=a|b)", "(a|b", "x*", "[a|b]"])
def test_non_literal_leaves_remain_regex(pattern: str) -> None:
    part = leaf_to_part(pattern, None)
    assert list(part) == ["regex", "ci"]


def test_empty_branch_is_regex() -> None:
    assert leaf_to_part("(a|)", None) == {"alt": [lit("a"), {"regex": "", "ci": True}]}


def test_anchors_dropped_and_structure_mapped() -> None:
    tree = node(
        "concat",
        leaf("^"),
        leaf("class"),
        node("opt", node("concat", leaf("[%s]+"), leaf("x", "N"))),
        node("or", leaf("\\d", None), leaf("y", "Y"), name="CODE"),
        node("star", leaf("a")),
        node("plus", leaf("b")),
        leaf("$"),
    )
    warnings: list[str] = []
    assert translate_tree(tree, warnings) == {
        "seq": [
            lit("class"),
            {
                "opt": {
                    "seq": [
                        {"regex": "[\\s\u00a0]+", "ci": True},
                        {"regex": "x", "ci": True, "name": "N"},
                    ]
                }
            },
            {"alt": [{"regex": "\\d", "ci": True}, {"regex": "y", "ci": True, "name": "Y"}]},
            {"star": lit("a")},
            {"plus": lit("b")},
        ]
    }
    assert warnings == ["dropped-node-name:CODE"]


def test_single_child_concat_collapses_and_anchor_only_is_empty_regex() -> None:
    assert translate_tree(node("concat", leaf("^"), leaf("x"), leaf("$")), []) == lit("x")
    assert translate_tree(node("concat", leaf("^"), leaf("$")), []) == {"regex": "", "ci": True}


def test_embedded_anchors_kept() -> None:
    assert translate_tree(leaf("^end[%s]?title$"), []) == {
        "regex": "^end[\\s\u00a0]?title$",
        "ci": True,
    }


def test_unknown_node_type_raises() -> None:
    with pytest.raises(ValueError, match="ub-x"):
        translate_node(node("ub-x"), [])


def test_translate_command_multiline_end_and_portability() -> None:
    cmd = command(
        node("concat", leaf("^"), leaf("a++", "P"), leaf("$")),
        leaf("^end$"),
        kind="multiline",
    )
    result = translate_command(cmd)
    assert result.kind == "multiline"
    assert result.parts == {"regex": "a++", "ci": True, "name": "P"}
    assert result.end == {"regex": "^end$", "ci": True}
    assert result.warnings == ("portability:possessive-quantifier",)


def test_translate_command_without_end() -> None:
    result = translate_command(command(leaf("^x$")))
    assert result.end is None
    assert result.warnings == ()


def test_join_for_decorator_without_end() -> None:
    result = translate_command(command(leaf("^x$"), kind="multiline", nbMaxLines=50))
    assert (result.kind, result.end, result.join_max_lines) == ("multiline", None, 50)


def test_bracket_without_end_has_no_join() -> None:
    result = translate_command(command(leaf("^x\\{$"), kind="multiline-bracket", nbMaxLines=3))
    assert result.join_max_lines is None


def test_plain_pattern_classes_are_case_sensitive() -> None:
    cls = "net.sourceforge.plantuml.eggs.PSystemColorsFactory"
    tree = node("concat", leaf("^"), leaf("a", "N"), node("opt", leaf("b[%s]")), leaf("$"))
    result = translate_command(command(tree, kind="opaque", cls=cls))
    assert result.parts == {
        "seq": [{"regex": "a", "name": "N"}, {"opt": {"regex": "b[\\s\u00a0]"}}]
    }
    literal = translate_command(command(leaf("go"), cls=cls)).parts
    assert literal == {"literal": "go", "ci": True}
