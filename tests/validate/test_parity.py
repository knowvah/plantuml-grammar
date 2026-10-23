"""Parity harness: totals, classification, exit codes, merge and pool plumbing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.validate import parity, parity_core, parity_io, parity_run
from tools.validate.parity_core import KIND_FR, build_report, count_totals, target_failures

from .parity_helpers import (
    BAD_BLOCK,
    GOOD_BLOCK,
    job,
    result,
    verdict,
    write_toy_models,
)

PIN = "pin"


@pytest.fixture(autouse=True)
def _pin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(parity, "default_pin", lambda: PIN)


def fake_corpus_results():
    """1 FR, 1 FA, 1 timeout and 1 clean block."""
    return [
        result("fr.puml", oracle=True, interp=verdict(False)),
        result("fa.puml", oracle=False, interp=verdict(True, diagram="CLASS"), otype=None),
        result("slow.puml", oracle=True, interp=verdict(False, "timeout")),
        result("ok.puml", oracle=True, interp=verdict(True, diagram="CLASS")),
    ]


def test_totals_count_each_discrepancy_once():
    totals = count_totals(fake_corpus_results())
    assert (totals["fr"], totals["fa"], totals["timeout"]) == (1, 1, 1)
    assert (totals["blocks"], totals["oracle_accepted"]) == (4, 3)


def test_timeout_is_neither_fr_nor_fa():
    slow = result("s.puml", oracle=True, interp=verdict(False, "timeout"))
    totals = count_totals([slow])
    assert (totals["timeout"], totals["fr"], totals["fa"]) == (1, 0, 0)


def test_diagram_mismatch_and_raw_fr_are_additive_kinds():
    block = result(
        "m.puml",
        oracle=True,
        interp=verdict(True, diagram="STATE"),
        raw=verdict(False),
    )
    totals = count_totals([block])
    assert (totals["diagram_mismatch"], totals["raw_fr"], totals["fr"]) == (1, 1, 0)
    raw_timeout = result("t.puml", oracle=True, interp=verdict(True), raw=verdict(False, "timeout"))
    assert count_totals([raw_timeout])["raw_fr"] == 0


def test_report_cases_follow_i6_shape():
    report = build_report(PIN, "vega", "class", fake_corpus_results(), {})
    assert (report["pin"], report["corpus"], report["family"]) == (PIN, "vega", "class")
    fr = next(c for c in report["cases"] if c["kind"] == KIND_FR)
    assert (fr["path"], fr["block"], fr["oracle"], fr["interp"]) == (
        "fr.puml",
        0,
        True,
        False,
    )
    assert (fr["class"], fr["note"]) == ("unclassified", "")
    assert fr["first_failure"] == {"line": 2, "text": "nonsense"}
    assert [c["path"] for c in report["cases"]] == sorted(c["path"] for c in report["cases"])


def test_classification_file_supplies_class_and_note(tmp_path: Path):
    (tmp_path / "class.yaml").write_text(
        'cases:\n  "fr.puml#0": {class: bug, note: fix the regex}\n'
        '  "vega:fa.puml#0": {class: semantic, note: duplicate id}\n'
        '  "other:fa.puml#0": {class: bug, note: wrong corpus}\n'
        "  broken: 3\n",
        encoding="utf-8",
    )
    classes = parity_io.load_classes("class", tmp_path)
    report = build_report(PIN, "vega", "class", fake_corpus_results(), classes)
    by_path = {c["path"]: c for c in report["cases"]}
    assert (by_path["fr.puml"]["class"], by_path["fr.puml"]["note"]) == ("bug", "fix the regex")
    assert (by_path["fa.puml"]["class"], by_path["fa.puml"]["note"]) == ("semantic", "duplicate id")
    assert by_path["slow.puml"]["class"] == "unclassified"


def test_flat_classification_and_missing_file(tmp_path: Path):
    (tmp_path / "flat.yaml").write_text('"a.puml#1": {class: bug, note: n}\n', encoding="utf-8")
    assert parity_io.load_classes("flat", tmp_path) == {"a.puml#1": {"class": "bug", "note": "n"}}
    assert parity_io.load_classes("absent", tmp_path) == {}
    (tmp_path / "empty.yaml").write_text("", encoding="utf-8")
    assert parity_io.load_classes("empty", tmp_path) == {}
    (tmp_path / "list.yaml").write_text("- 1\n", encoding="utf-8")
    assert parity_io.load_classes("list", tmp_path) == {}


def _report(corpus: str, fr: int, accepted: int, unclassified: bool = False):
    cases = [
        {
            "kind": "fr",
            "class": "unclassified" if unclassified else "bug",
            "path": "p",
            "block": i,
            "note": "",
        }
        for i in range(fr)
    ]
    totals = {k: 0 for k in parity_core.TOTAL_KEYS} | {"fr": fr, "oracle_accepted": accepted}
    return {"pin": PIN, "corpus": corpus, "family": "f", "totals": totals, "cases": cases}


def test_targets_zero_fr_on_vega_and_plantuml_ts():
    assert target_failures(_report("vega", 0, 10)) == []
    assert target_failures(_report("vega", 1, 10)) == ["vega: 1 false reject(s), target 0"]
    assert len(target_failures(_report("plantuml-ts", 2, 10))) == 1


def test_targets_pdiff_rate_and_classification():
    assert target_failures(_report("pdiff", 2, 100)) == []
    rate = target_failures(_report("pdiff", 3, 100))
    assert rate == ["pdiff: FR rate 3.00% exceeds 2%"]
    unclassified = target_failures(_report("pdiff", 1, 100, unclassified=True))
    assert unclassified == ["pdiff: 1 unclassified FR/FA case(s)"]
    assert parity_core.fr_rate({"fr": 1, "oracle_accepted": 0}) == 0.0


def _deps(tmp_path: Path, oracle_blocks, interp_outcome):
    root = tmp_path / "corpus"
    root.mkdir(exist_ok=True)
    files = []
    for name, text in oracle_blocks.items():
        path = root / name
        path.write_text(text, encoding="utf-8")
        files.append(path)

    def oracle(paths):
        return {
            str(p): [
                {
                    "index": 0,
                    "start_keyword": "@startuml",
                    "accepted": "good" in p.name,
                    "diagram_type": "CLASS" if "good" in p.name else None,
                    "error_line": None,
                    "preproc": oracle_blocks[p.name].split("\n"),
                }
            ]
            for p in paths
        }

    return parity.Deps(lambda _c: (root, files), oracle, interp_outcome)


def _opts(tmp_path: Path, **extra) -> parity.Options:
    models = write_toy_models(tmp_path / "models")
    return parity.Options(
        corpora=("vega",),
        model_dir=models,
        out_dir=tmp_path / "out",
        classify_dir=tmp_path / "classify",
        **extra,
    )


def test_run_exits_nonzero_on_false_reject_and_writes_slice(tmp_path: Path, capsys):
    deps = _deps(tmp_path, {"good.puml": GOOD_BLOCK}, lambda _j: (verdict(False), None))
    code = parity.run(_opts(tmp_path, family="class"), deps)
    out = capsys.readouterr()
    assert code == parity.EXIT_TARGETS
    assert "TARGET MISSED: vega: 1 false reject(s)" in out.err
    assert "vega         class            blocks=1 fr=1 fa=0 timeout=0" in out.out
    written = json.loads((tmp_path / "out" / "vega" / "class.json").read_text())
    assert written["totals"]["fr"] == 1


def test_run_exits_zero_when_everything_agrees(tmp_path: Path):
    agree = verdict(True, diagram="CLASS", model="toydiagram")
    deps = _deps(
        tmp_path,
        {"good.puml": GOOD_BLOCK, "bad.puml": BAD_BLOCK},
        lambda j: (agree, None) if j.oracle else (verdict(False), None),
    )
    assert parity.run(_opts(tmp_path), deps) == parity.EXIT_OK
    slices = sorted(p.stem for p in (tmp_path / "out" / "vega").glob("*.json"))
    assert slices == ["class", "unclassified"]


def test_run_reports_a_missing_corpus(tmp_path: Path, capsys):
    deps = _deps(tmp_path, {"good.puml": GOOD_BLOCK}, lambda _j: (verdict(True), None))

    def boom(_corpus):
        raise parity.ConfigError("CORPUS_VEGA not found")

    broken = parity.Deps(boom, deps.oracle, deps.interp)
    assert parity.run(_opts(tmp_path), broken) == parity.EXIT_ENV
    assert "CORPUS_VEGA not found" in capsys.readouterr().err


def test_families_filter_skips_jobs_that_cannot_match():
    jobs = [job("a", "x", oracle=True, otype="SEQUENCE"), job("b", "y", oracle=True, otype="CLASS")]
    kept = [j.path for j in jobs if parity.needs_job(j, ["class"])]
    assert kept == ["b"]
    assert parity.needs_job(job("c", "z", oracle=False, otype=None), ["gantt"])
    assert parity.needs_job(jobs[0], ["common"])
    assert parity.wanted_families("gantt") == ("gantt",)
    assert "unclassified" in parity.wanted_families(None)


def test_assign_families_uses_interpreter_factory_for_rejected_blocks():
    jobs = [job("a", GOOD_BLOCK, oracle=False, otype=None)]
    outcomes = [(verdict(True, model="m"), None)]
    assert parity.assign_families(jobs, outcomes, {"m": "GanttDiagramFactory"}) == ["gantt"]
    assert parity.assign_families(jobs, outcomes, {}) == ["unclassified"]


def _slice(family: str, fr: int = 0, blocks: int = 3):
    rep = _report("vega", fr, blocks)
    rep["family"] = family
    rep["totals"]["blocks"] = blocks
    return rep


def test_merge_combines_two_families_and_excludes_overlays(tmp_path: Path, capsys):
    out, reports = tmp_path / "parity", tmp_path / "reports"
    for rep in (_slice("class"), _slice("sequence", blocks=2), _slice("common", blocks=5)):
        parity_io.write_json(parity_io.slice_path(out, "vega", rep["family"]), rep)
    assert parity.merge(["vega", "pdiff"], out, reports) == parity.EXIT_OK
    merged = json.loads((reports / "parity-vega.json").read_text())
    assert sorted(merged["families"]) == ["class", "common", "sequence"]
    assert merged["families"]["common"]["overlay"] is True
    assert merged["totals"]["blocks"] == 5
    md = (reports / "parity-vega.md").read_text()
    assert "| class | 3 |" in md and "| common (overlay) | 5 |" in md
    assert "| **total** | 5 |" in md
    assert "no slices for pdiff" in capsys.readouterr().err


def test_merge_fails_when_a_target_is_missed(tmp_path: Path):
    out, reports = tmp_path / "parity", tmp_path / "reports"
    rep = _slice("class", fr=1)
    parity_io.write_json(parity_io.slice_path(out, "vega", "class"), rep)
    assert parity.merge(["vega"], out, reports) == parity.EXIT_TARGETS
    md = (reports / "parity-vega.md").read_text()
    assert "- class: `p#0` fr (bug)" in md


def test_merge_pins_differing_are_listed():
    a, b = _slice("a"), _slice("b")
    b["pin"] = "other"
    merged = parity_core.merge_reports("vega", [a, b], ())
    assert merged["pin"] == ["other", PIN]


def test_main_parses_run_and_merge(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    seen = {}
    monkeypatch.setattr(parity, "run", lambda opts: seen.setdefault("opts", opts) and 0)
    assert parity.main(["--corpus", "vega", "--family", "gantt", "--timeout", "7"]) == 0
    opts = seen["opts"]
    assert (opts.corpora, opts.family, opts.timeout_s) == (("vega",), "gantt", 7.0)
    out = tmp_path / "p"
    code = parity.main(["merge", "--corpus", "vega", "--out", str(out), "--reports", str(tmp_path)])
    assert code == parity.EXIT_OK
    assert parity._corpus_names("all") == ("vega", "plantuml-ts", "pdiff")


def test_collect_jobs_pairs_raw_blocks_and_skips_oracle_errors(tmp_path: Path):
    two = f"{GOOD_BLOCK}\n{GOOD_BLOCK}\n"
    a, b, c = (tmp_path / n for n in ("a.puml", "b.puml", "c.puml"))
    a.write_text(two, encoding="utf-8")
    b.write_text(GOOD_BLOCK, encoding="utf-8")
    c.write_text("", encoding="utf-8")

    def block(i, preproc):
        return {
            "index": i,
            "start_keyword": "@startuml",
            "accepted": True,
            "diagram_type": "CLASS",
            "error_line": None,
            "preproc": preproc,
        }

    verdicts = {
        str(a): [block(0, ["@startuml", "class A", "@enduml"]), block(1, [])],
        str(b): [block(0, []), block(1, [])],
        str(c): [{"index": 0, "error": "boom"}],
    }
    jobs, skipped = parity_run.collect_jobs(tmp_path, verdicts)
    assert skipped == ["c.puml"]
    assert [(j.path, j.block, j.raw_text is not None) for j in jobs] == [
        ("a.puml", 0, True),
        ("a.puml", 1, True),
        ("b.puml", 0, False),
        ("b.puml", 1, False),
    ]
    assert jobs[0].text == GOOD_BLOCK
    assert jobs[1].text == GOOD_BLOCK
    assert jobs[2].text == ""


def test_judge_runs_l2_and_raw_with_real_interpreter(tmp_path: Path):
    models = parity_run.load_models(write_toy_models(tmp_path / "m"))
    assert parity_run.has_preproc(models) is False
    config = parity_run.RunConfig(tmp_path, 5.0, True)
    good = parity_run.judge(models, job("g", GOOD_BLOCK, oracle=True), config)
    assert (good[0]["accepted"], good[0]["diagram"], good[0]["model"]) == (
        True,
        "CLASS",
        "toydiagram",
    )
    assert good[1] is not None and good[1]["accepted"] is True
    bad = parity_run.judge(models, job("b", BAD_BLOCK, oracle=True), config)
    assert bad[0]["accepted"] is False and bad[0]["first_failure"]["line"] == 2
    no_raw = parity_run.judge(
        models, job("g", GOOD_BLOCK, oracle=True), parity_run.RunConfig(tmp_path, 5.0, False)
    )
    assert no_raw[1] is None


def test_judge_survives_engine_crash(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    models = parity_run.load_models(write_toy_models(tmp_path / "m"))
    config = parity_run.RunConfig(tmp_path, 5.0, True)

    def crash(*_args, **_kwargs):
        raise ValueError("kaboom")

    monkeypatch.setattr(parity_run, "accepts", crash)
    crashed = parity_run.judge(models, job("g", GOOD_BLOCK, oracle=True), config)
    assert crashed[0]["status"] == "error"
    assert crashed[0]["first_failure"]["text"] == "ValueError: kaboom"
    assert crashed[1] is None
    raw_only = parity_run._raw_verdict(models, "x", 1.0)
    assert raw_only is not None and raw_only["status"] == "error"


def test_run_interp_pool_matches_serial_in_order(tmp_path: Path):
    models_dir = write_toy_models(tmp_path / "m")
    config = parity_run.RunConfig(models_dir, 5.0, False)
    jobs = [job(f"j{i}", GOOD_BLOCK if i % 3 else BAD_BLOCK, oracle=True) for i in range(80)]
    serial = parity_run.run_interp(jobs, config, workers=1)
    pooled = parity_run.run_interp(jobs, config, workers=2)
    assert [o[0]["accepted"] for o in pooled] == [o[0]["accepted"] for o in serial]
    assert [o[0]["accepted"] for o in pooled] == [bool(i % 3) for i in range(80)]


def test_default_list_resolves_root_and_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "x.puml").write_text(GOOD_BLOCK, encoding="utf-8")
    monkeypatch.setenv("CORPUS_VEGA", str(tmp_path))
    root, files = parity.default_list("vega")
    assert root == tmp_path
    assert files == [tmp_path / "sub" / "x.puml"]
