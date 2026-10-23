from pathlib import Path

from tools.config import Config
from tools.validate.corpus import enumerate_corpora


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("@startuml\n@enduml\n")
    return path


def _config(tmp_path: Path) -> Config:
    return Config(
        jar=tmp_path / "x.jar",
        src=tmp_path,
        vega=tmp_path / "vega",
        plantuml_ts=tmp_path / "ts",
        pdiff=tmp_path / "pdiff",
    )


def test_enumerates_all_corpora_with_family_hints(tmp_path):
    cfg = _config(tmp_path)
    v = _touch(cfg.vega / "svg" / "a.puml")
    _touch(cfg.vega / "svg" / "ignore.txt")
    s = _touch(cfg.plantuml_ts / "class" / "c1.puml")
    loose = _touch(cfg.plantuml_ts / "loose.puml")
    p = _touch(cfg.pdiff / "dbhum" / "p1.puml")

    got = list(enumerate_corpora(cfg))

    assert got == [
        ("vega", v, None),
        ("plantuml-ts", s, "class"),
        ("plantuml-ts", loose, None),
        ("pdiff", p, None),
    ]


def test_selects_named_corpora_only(tmp_path):
    cfg = _config(tmp_path)
    _touch(cfg.vega / "a.puml")
    p = _touch(cfg.pdiff / "p.puml")

    assert list(enumerate_corpora(cfg, ["pdiff"])) == [("pdiff", p, None)]


def test_unrequested_missing_corpora_are_not_checked(tmp_path):
    cfg = _config(tmp_path)
    a = _touch(cfg.vega / "a.puml")

    assert list(enumerate_corpora(cfg, ["vega"])) == [("vega", a, None)]


def test_missing_requested_corpus_raises(tmp_path):
    import pytest

    from tools.config import ConfigError

    with pytest.raises(ConfigError, match="CORPUS_PDIFF"):
        list(enumerate_corpora(_config(tmp_path), ["pdiff"]))
