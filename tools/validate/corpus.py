"""Enumerate the read-only corpora as (corpus, path, family_hint) triples."""

from __future__ import annotations

import os
from collections.abc import Iterator, Sequence
from pathlib import Path

from tools.config import ENV_VARS, Config, ConfigError, resolve

VEGA = "vega"
PLANTUML_TS = "plantuml-ts"
PDIFF = "pdiff"
CORPORA: tuple[str, ...] = (VEGA, PLANTUML_TS, PDIFF)

_CONFIG_NAME = {VEGA: "vega", PLANTUML_TS: "plantuml_ts", PDIFF: "pdiff"}
PUML_GLOB = "*.puml"


def _root(cfg: Config, corpus: str) -> Path:
    root: Path = getattr(cfg, _CONFIG_NAME[corpus])
    if not root.is_dir():
        env = ENV_VARS[_CONFIG_NAME[corpus]]
        raise ConfigError(f"{env} not found at {root}; set {env}")
    return root


def _family_hint(corpus: str, root: Path, path: Path) -> str | None:
    if corpus != PLANTUML_TS:
        return None
    parts = path.relative_to(root).parts
    return parts[0] if len(parts) > 1 else None


def enumerate_corpora(
    cfg: Config | None = None, corpora: Sequence[str] = CORPORA
) -> Iterator[tuple[str, Path, str | None]]:
    """Yield (corpus, path, family_hint) in sorted path order per corpus."""
    cfg = cfg or resolve(os.environ, Path.home())
    for corpus in corpora:
        root = _root(cfg, corpus)
        for path in sorted(root.rglob(PUML_GLOB)):
            yield corpus, path, _family_hint(corpus, root, path)
