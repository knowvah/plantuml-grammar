"""Locations of the pinned jar, upstream source and corpora.

`resolve` is pure (env + home in, Config out); `require` reads the process
environment and checks that the path exists. The upstream pin has one source of
truth, `upstream-pin.json`; `PIN_SHA` is read from it at import.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PIN_FILE = "upstream-pin.json"


def load_pin(root: Path) -> dict[str, str]:
    """The ``upstream-pin.json`` under ``root`` (``sha``, ``version``, ``repo``)."""
    pin: dict[str, str] = json.loads((root / PIN_FILE).read_text(encoding="utf-8"))
    return pin


PIN_SHA = load_pin(REPO_ROOT)["sha"]

ENV_VARS: dict[str, str] = {
    "jar": "PLANTUML_JAR",
    "src": "PLANTUML_SRC",
    "vega": "CORPUS_VEGA",
    "plantuml_ts": "CORPUS_PLANTUML_TS",
    "pdiff": "CORPUS_PDIFF",
}

VEGA_SUBDIR = "src/test/resources/vega"


class ConfigError(Exception):
    """A required external input (jar, source tree, corpus) is missing."""


@dataclass(frozen=True)
class Config:
    jar: Path
    src: Path
    vega: Path
    plantuml_ts: Path
    pdiff: Path


def _path(env: Mapping[str, str], name: str, home: Path, default: Path) -> Path:
    raw = env.get(ENV_VARS[name])
    if not raw:
        return default
    if raw == "~" or raw.startswith("~/"):
        return home / raw[2:]
    return Path(raw)


def resolve(env: Mapping[str, str], home: Path) -> Config:
    stock = home / "git/knowvah/plantuml-ts/oracle/dist/stock"
    src = _path(env, "src", home, home / "git/plantuml")
    return Config(
        jar=_path(env, "jar", home, stock / f"plantuml-stock-{PIN_SHA}.jar"),
        src=src,
        vega=_path(env, "vega", home, src / VEGA_SUBDIR),
        plantuml_ts=_path(env, "plantuml_ts", home, home / "git/knowvah/plantuml-ts/tests/corpus"),
        pdiff=_path(env, "pdiff", home, home / "git/pdiff"),
    )


def require(name: str, cfg: Config | None = None) -> Path:
    if name not in ENV_VARS:
        raise ConfigError(f"unknown config name '{name}'; expected one of {sorted(ENV_VARS)}")
    cfg = cfg or resolve(os.environ, Path.home())
    path: Path = getattr(cfg, name)
    if not path.exists():
        env = ENV_VARS[name]
        raise ConfigError(f"{env} not found at {path}; set {env}")
    return path
