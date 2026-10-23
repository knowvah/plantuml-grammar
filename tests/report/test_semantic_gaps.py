"""Semantic gaps report: false accepts classified `semantic`, grouped by kind."""

import json

import pytest
import yaml

from tools.report import semantic_gaps as sg
from tools.translate.provenance import ProvenanceError

CITE = "src/main/java/net/sourceforge/plantuml/sequencediagram/SequenceDiagram.java:207-210"


def case(path, family="sequence", kind="fa", cls="semantic", block=0):
    return {"path": path, "block": block, "family": family, "kind": kind, "class": cls}


def merged(corpus, *cases):
    return {"corpus": corpus, "cases": list(cases)}


NOTE_KINDS = [
    ("preprocessor error: %dirpath() has arity 0", sg.KIND_PREPROC),
    ("create then a message: pendingCreate check (state)", sg.KIND_STATE),
    ("class X then class X.Encoding: Bad hierarchy", sg.KIND_STATE),
    ("link endpoint c belongs to another concurrent region", sg.KIND_STATE),
    ("map CapitalCity defined twice: Map already exists", sg.KIND_DUPLICATE),
    ("`class Order` fails: Bad name", sg.KIND_DUPLICATE),
    ("`note left of compo` before compo exists: Not known: compo", sg.KIND_REFERENCE),
    ("unknown arrow color: NoSuchColorException", sg.KIND_REFERENCE),
    ("task lookup by name: [T2] is declared on a later line", sg.KIND_REFERENCE),
    ("link endpoint ChildMode1.A resolves under the current group", sg.KIND_REFERENCE),
    ("`jar:x` names no internal sprite", sg.KIND_REFERENCE),
    ('copy of nixuje: "No such internal sprite"', sg.KIND_REFERENCE),
    ("item level 2 under the root (cross-line, leading blanks)", sg.KIND_CONTEXT),
    ("20-year limit: date arithmetic over the whole diagram", sg.KIND_CONTEXT),
    ("something nobody anticipated", sg.KIND_OTHER),
    ("", sg.KIND_OTHER),
]


@pytest.mark.parametrize(("note", "expected"), NOTE_KINDS)
def test_gap_kind_follows_the_note(note, expected):
    assert sg.gap_kind(note) == expected


def test_kind_order_is_the_report_order():
    assert sg.KIND_ORDER == (
        sg.KIND_REFERENCE,
        sg.KIND_DUPLICATE,
        sg.KIND_CONTEXT,
        sg.KIND_STATE,
        sg.KIND_PREPROC,
        sg.KIND_OTHER,
    )


def test_normalize_cite_strips_the_package_prefix_only_for_display():
    assert sg.short_cite(CITE) == "sequencediagram/SequenceDiagram.java:207-210"
    assert sg.short_cite("src/main/java/net/atmp/CucaDiagram.java:282") == (
        "net/atmp/CucaDiagram.java:282"
    )


def test_collect_keeps_only_semantic_false_accepts():
    reports = {
        "vega": merged(
            "vega",
            case("a.puml"),
            case("b.puml", kind="timeout"),
            case("c.puml", cls="bug"),
            case("d.puml", cls="unclassified"),
        )
    }
    classes = {
        "sequence": {"a.puml#0": {"class": "semantic", "note": "pendingCreate", "cite": CITE}}
    }
    gaps = sg.collect(reports, classes)
    assert [(g.corpus, g.path, g.kind, g.cite) for g in gaps] == [
        ("vega", "a.puml", sg.KIND_STATE, CITE)
    ]


def test_collect_prefers_the_corpus_scoped_key():
    reports = {"pdiff": merged("pdiff", case("x/a.puml"))}
    classes = {
        "sequence": {
            "x/a.puml#0": {"note": "defined twice", "cite": "src/main/java/A.java:1"},
            "pdiff:x/a.puml#0": {"note": "Not known: q", "cite": "src/main/java/B.java:2"},
        }
    }
    (gap,) = sg.collect(reports, classes)
    assert (gap.kind, gap.cite) == (sg.KIND_REFERENCE, "src/main/java/B.java:2")


def test_collect_without_a_classification_entry_uses_empty_note_and_cite():
    (gap,) = sg.collect({"vega": merged("vega", case("a.puml"))}, {})
    assert (gap.kind, gap.note, gap.cite) == (sg.KIND_OTHER, "", "")


def gap(corpus, family, path, kind, cite, note="n"):
    return sg.Gap(corpus, family, path, 0, kind, cite, note)


def test_render_groups_by_kind_with_counts_per_family_and_cites():
    gaps = [
        gap("plantuml-ts", "class", "a.puml", sg.KIND_DUPLICATE, "src/main/java/net/atmp/X.java:3"),
        gap("pdiff", "class", "b.puml", sg.KIND_DUPLICATE, "src/main/java/net/atmp/X.java:3"),
        gap("pdiff", "timing", "c.puml", sg.KIND_REFERENCE, "src/main/java/net/atmp/Y.java:9"),
    ]
    text = sg.render(gaps, {})
    assert text.index("## Reference resolution") < text.index("## Duplicate declarations")
    assert "| class | 0 | 1 | 1 | 2 |" in text
    assert "| timing | 0 | 0 | 1 | 1 |" in text
    assert "`net/atmp/X.java:3`" in text
    assert "## Context-dependent" not in text
    assert "Total: 3 false accepts (vega 0, plantuml-ts 1, pdiff 2)." in text


def test_render_lists_each_cite_once_with_its_count_and_a_note():
    gaps = [
        gap("pdiff", "class", "a.puml", sg.KIND_DUPLICATE, "src/main/java/A.java:3", "first"),
        gap("pdiff", "class", "b.puml", sg.KIND_DUPLICATE, "src/main/java/A.java:3", "second"),
    ]
    text = sg.render(gaps, {})
    assert text.count("`A.java:3`") == 1
    assert "| `A.java:3` | 2 | first |" in text


def test_render_with_no_gaps_says_so():
    assert "Total: 0 false accepts" in sg.render([], {})


def test_render_counts_other_parity_differences_from_totals():
    totals = {
        "vega": {"timeout": 0, "diagram_mismatch": 4, "raw_fr": 3},
        "pdiff": {"timeout": 35, "diagram_mismatch": 49, "raw_fr": 198},
    }
    text = sg.render([], totals)
    assert "| pdiff | 35 | 49 | 198 |" in text
    assert "| vega | 0 | 4 | 3 |" in text


def test_load_reports_reads_merged_files_and_skips_missing_corpora(tmp_path):
    (tmp_path / "parity-vega.json").write_text(json.dumps(merged("vega", case("a.puml"))))
    found = sg.load_reports(tmp_path, ("vega", "pdiff"))
    assert list(found) == ["vega"]
    assert found["vega"]["cases"][0]["path"] == "a.puml"


def test_load_classes_merges_every_family_file(tmp_path):
    doc = {"cases": {"a.puml#0": {"class": "semantic", "note": "n", "cite": CITE}}}
    (tmp_path / "sequence.yaml").write_text(yaml.safe_dump(doc))
    (tmp_path / "empty.yaml").write_text("")
    classes = sg.load_classes(tmp_path)
    assert classes["sequence"]["a.puml#0"]["cite"] == CITE
    assert "empty" not in classes


def test_main_writes_the_report(tmp_path, capsys):
    reports, classify, out = tmp_path / "reports", tmp_path / "classify", tmp_path / "docs" / "g.md"
    reports.mkdir()
    classify.mkdir()
    (reports / "parity-vega.json").write_text(
        json.dumps({**merged("vega", case("a.puml")), "totals": {"timeout": 1}})
    )
    (classify / "sequence.yaml").write_text(
        yaml.safe_dump(
            {"cases": {"a.puml#0": {"class": "semantic", "note": "defined twice", "cite": CITE}}}
        )
    )
    code = sg.main(["--reports", str(reports), "--classify", str(classify), "--out", str(out)])
    assert code == 0
    assert "## Duplicate declarations" in out.read_text(encoding="utf-8")
    assert str(out) in capsys.readouterr().err


def test_cites_resolve_at_the_pin_against_a_fake_reader():
    files = {"src/main/java/net/atmp/X.java": "a\nb\nc\n"}

    def reader(path):
        if path not in files:
            raise ProvenanceError(path)
        return files[path]

    gaps = [
        gap("pdiff", "c", "a", sg.KIND_OTHER, "src/main/java/net/atmp/X.java:2-3"),
        gap("pdiff", "c", "b", sg.KIND_OTHER, "src/main/java/net/atmp/X.java:9"),
        gap("pdiff", "c", "c", sg.KIND_OTHER, "src/main/java/net/atmp/Nope.java:1"),
        gap("pdiff", "c", "d", sg.KIND_OTHER, ""),
    ]
    assert sg.unresolved_cites(gaps, reader) == [
        "src/main/java/net/atmp/X.java:9",
        "src/main/java/net/atmp/Nope.java:1",
        "",
    ]


def test_main_check_cites_fails_on_an_unresolved_cite(tmp_path, monkeypatch, capsys):
    reports, classify = tmp_path / "reports", tmp_path / "classify"
    reports.mkdir()
    classify.mkdir()
    (reports / "parity-vega.json").write_text(json.dumps(merged("vega", case("a.puml"))))
    (classify / "sequence.yaml").write_text(
        yaml.safe_dump({"cases": {"a.puml#0": {"note": "x", "cite": "src/main/java/A.java:7"}}})
    )

    def missing(_path):
        raise ProvenanceError("gone")

    monkeypatch.setattr(sg, "git_reader", lambda: missing)
    argv = ["--reports", str(reports), "--classify", str(classify), "--out", str(tmp_path / "o.md")]
    assert sg.main([*argv, "--check-cites"]) == 1
    assert "src/main/java/A.java:7" in capsys.readouterr().err


def test_render_appends_the_measured_explanations_after_the_table():
    text = sg.render([], {"vega": {"timeout": 1}})
    assert text.index("| vega | 1 | 0 | 0 |") < text.index("**Interpreter timeouts.**")
    assert text.rstrip().endswith("See `.agent-notes/T14.md`.")
