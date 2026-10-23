from tools.translate.dedupe import Unit, canonical, dedupe, name_hint, weight

LONG = "x" * 50
URL = {"regex": LONG, "name": "URL"}


def unit(model: str, *extra: dict) -> Unit:
    return Unit(model, ({"seq": [{"literal": "a", "ci": True}, *extra]},))


def test_repeated_subtree_in_one_model_is_local() -> None:
    result = dedupe([unit("m1", URL), unit("m1", URL), unit("m1", URL)])
    assert result.variables == {"URL": URL}
    assert result.owners == {"URL": "m1"}
    assert result.trees[0] == [{"seq": [{"literal": "a", "ci": True}, {"ref": "URL"}]}]


def test_repeated_across_models_is_shared() -> None:
    result = dedupe([unit("m1", URL), unit("m2", URL), unit("m1", URL)])
    assert result.owners == {"URL": None}


def test_two_commands_do_not_qualify() -> None:
    result = dedupe([unit("m1", URL), unit("m1", URL), unit("m1")])
    assert result.variables == {}
    assert result.trees[0] == [{"seq": [{"literal": "a", "ci": True}, URL]}]


def test_light_subtree_does_not_qualify() -> None:
    tiny = {"regex": "[\\s]+"}
    assert dedupe([unit("m", tiny)] * 3).variables == {}


def test_nested_variables_and_name_collisions() -> None:
    inner = {"regex": LONG, "name": "COLOR"}
    outer = {"seq": [inner, {"regex": "y" * 50, "name": "COLOR"}]}
    units = [
        unit("m1", outer),
        unit("m2", outer),
        unit("m1", outer),
        unit("m2", inner),
        unit("m2", inner),
        unit("m1", inner),
    ]
    result = dedupe(units)
    assert set(result.variables) == {"COLOR", "COLOR_2"}
    assert result.variables["COLOR"] == {"seq": [{"ref": "COLOR_2"}, outer["seq"][1]]}
    assert result.owners == {"COLOR": None, "COLOR_2": None}
    assert result.trees[3] == [{"seq": [{"literal": "a", "ci": True}, {"ref": "COLOR_2"}]}]


def test_name_hint_variants() -> None:
    assert name_hint({"regex": "x", "name": "back color"}) == "BACK_COLOR"
    assert name_hint({"regex": "x", "name": "1st"}) == "V_1ST"
    assert name_hint({"seq": [{"opt": {"regex": "x", "name": "Q"}}]}) == "Q"
    assert name_hint({"regex": "x"}) == "COMMON"


def test_weight_and_canonical() -> None:
    part = {"seq": [{"regex": "abc"}, {"opt": {"literal": "de", "ci": True}}]}
    assert weight(part) == 5
    assert canonical({"b": 1, "a": 2}) == canonical({"a": 2, "b": 1})
