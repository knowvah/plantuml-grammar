import json
from pathlib import Path

import pytest

from tools import config
from tools.config import ConfigError, require, resolve

HOME = Path("/home/tester")
REPO_ROOT = Path(__file__).resolve().parents[1]
PIN_SHA = json.loads((REPO_ROOT / "upstream-pin.json").read_text())["sha"]
STOCK_JAR = HOME / "git/knowvah/plantuml-ts/oracle/dist/stock" / f"plantuml-stock-{PIN_SHA}.jar"


def test_resolve_defaults_when_env_empty():
    cfg = resolve({}, HOME)
    assert cfg.jar == STOCK_JAR
    assert cfg.src == HOME / "git/plantuml"
    assert cfg.vega == HOME / "git/plantuml/src/test/resources/vega"
    assert cfg.plantuml_ts == HOME / "git/knowvah/plantuml-ts/tests/corpus"
    assert cfg.pdiff == HOME / "git/pdiff"


def test_resolve_honours_env_overrides():
    env = {
        "PLANTUML_JAR": "/opt/p.jar",
        "PLANTUML_SRC": "/src/plantuml",
        "CORPUS_VEGA": "/c/vega",
        "CORPUS_PLANTUML_TS": "/c/ts",
        "CORPUS_PDIFF": "/c/pdiff",
    }
    cfg = resolve(env, HOME)
    assert cfg.jar == Path("/opt/p.jar")
    assert cfg.src == Path("/src/plantuml")
    assert cfg.vega == Path("/c/vega")
    assert cfg.plantuml_ts == Path("/c/ts")
    assert cfg.pdiff == Path("/c/pdiff")


def test_vega_default_follows_plantuml_src():
    cfg = resolve({"PLANTUML_SRC": "/src/plantuml"}, HOME)
    assert cfg.vega == Path("/src/plantuml/src/test/resources/vega")


def test_resolve_expands_user_in_env_values():
    cfg = resolve({"PLANTUML_JAR": "~/x.jar"}, HOME)
    assert cfg.jar == HOME / "x.jar"


def test_require_missing_path_names_path_and_env(monkeypatch):
    monkeypatch.setenv("PLANTUML_JAR", "/nope.jar")
    with pytest.raises(ConfigError) as exc:
        require("jar")
    assert str(exc.value) == "PLANTUML_JAR not found at /nope.jar; set PLANTUML_JAR"


def test_require_existing_path_returns_it(tmp_path, monkeypatch):
    jar = tmp_path / "p.jar"
    jar.write_bytes(b"")
    monkeypatch.setenv("PLANTUML_JAR", str(jar))
    assert require("jar") == jar


def test_require_uses_supplied_config(tmp_path):
    cfg = resolve({"CORPUS_PDIFF": str(tmp_path)}, HOME)
    assert require("pdiff", cfg) == tmp_path


def test_require_unknown_name_raises_config_error():
    with pytest.raises(ConfigError) as exc:
        require("bogus", resolve({}, HOME))
    assert "unknown config name 'bogus'" in str(exc.value)


def test_env_var_table_covers_every_field():
    assert set(config.ENV_VARS) == {"jar", "src", "vega", "plantuml_ts", "pdiff"}


def test_load_pin_reads_the_pin_file(tmp_path):
    pin = {"sha": "abc123", "version": "9.9", "repo": "https://example.invalid/p"}
    (tmp_path / config.PIN_FILE).write_text(json.dumps(pin))
    assert config.load_pin(tmp_path) == pin


def test_pin_sha_comes_from_upstream_pin_json():
    assert config.PIN_SHA == PIN_SHA
    assert config.load_pin(config.REPO_ROOT)["sha"] == config.PIN_SHA
