"""Block-to-family decisions."""

import pytest

from tools.report import families
from tools.report.families import family_of, in_family


def test_every_family_task_has_one_entry():
    assert families.FAMILY_IDS == (
        "common",
        "sequence",
        "class",
        "description",
        "state",
        "activity3",
        "activity-legacy",
        "timing",
        "gantt",
        "mindmap-wbs",
        "nwdiag-packet",
        "salt",
        "json",
        "misc-charts",
        "board-files-git",
        "meta-diagrams",
        "style",
        "single-line",
    )
    assert families.BLOCK_FAMILY_IDS == tuple(
        f for f in families.FAMILY_IDS if f not in ("common", "style")
    )


@pytest.mark.parametrize(
    ("dtype", "expected"),
    [
        ("SEQUENCE", "sequence"),
        ("OBJECT", "class"),
        ("USECASE", "description"),
        ("WBS", "mindmap-wbs"),
        ("PACKET", "nwdiag-packet"),
        ("YAML", "json"),
        ("CHEN_EER", "misc-charts"),
        ("GIT", "board-files-git"),
        ("SPRITES", "meta-diagrams"),
        ("CRASH", "single-line"),
        ("NEVER_HEARD_OF_IT", "unclassified"),
    ],
)
def test_oracle_type_decides_the_family(dtype, expected):
    assert family_of(dtype, "SequenceDiagramFactory", "@startuml") == expected


def test_activity_uses_interpreter_factory_then_text_markers():
    assert family_of("ACTIVITY", "ActivityDiagramFactory", "start") == "activity-legacy"
    assert family_of("ACTIVITY", "ActivityDiagramFactory3", "(*) --> a") == "activity3"
    assert family_of("ACTIVITY", None, "@startuml\n(*) --> a\n@enduml") == "activity-legacy"
    assert family_of("ACTIVITY", "ClassDiagramFactory", "@startuml\nstart\n@enduml") == "activity3"
    assert family_of("ACTIVITY", None, "x\n===B===\n") == "activity-legacy"


def test_rejected_blocks_fall_back_to_factory_then_keyword_then_unclassified():
    assert family_of(None, "GanttDiagramFactory", "@startuml") == "gantt"
    assert family_of(None, None, "  @startMindmap\n* a") == "mindmap-wbs"
    assert family_of(None, None, "@startuml\nx") == "unclassified"
    assert family_of(None, None, "@startzzz\nx") == "unclassified"
    assert family_of(None, None, "no start line") == "unclassified"


@pytest.mark.parametrize("keyword", ["crash", "dot", "ditaa", "math", "latex"])
def test_rejected_single_line_keywords_are_classified_by_start_keyword(keyword):
    assert family_of(None, None, f"@start{keyword}\nx\n@end{keyword}") == "single-line"
    assert family_of(None, None, f"@start{keyword.upper()}") == "single-line"


def test_candidates_before_the_interpreter_runs():
    assert families.candidate_families("SEQUENCE") == {"sequence"}
    assert families.candidate_families("ACTIVITY") == {"activity3", "activity-legacy"}
    assert families.candidate_families("WEIRD") == {"unclassified"}
    assert "gantt" in families.candidate_families(None)


def test_overlay_families_select_by_content():
    assert in_family("common", "gantt", "anything")
    assert in_family("style", "class", "<style>\nclass{}\n</style>")
    assert not in_family("style", "class", "class A")
    assert in_family("class", "class", "x") and not in_family("class", "state", "x")
