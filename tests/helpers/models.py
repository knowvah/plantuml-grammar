"""The repository model, loaded and resolved once per process.

``load_dir(model/)`` plus ``resolve`` takes about 14 s. Every family, layer and emitter
test module used to do it on its own, which was about 80% of the suite's run time. The
two functions here are cached for the life of the process (once per pytest-xdist worker),
so a module's fixture costs nothing after the first use.

The results are shared, so treat them as read-only: ``Model`` and ``ResolvedModel`` are
frozen, but their ``contexts`` hold ordinary dicts and lists. A test that needs to change
them works on a copy (``copy.deepcopy``) or builds its own models (``test_common``'s
probes wrap the shared dict in a new one).
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from tools.model import Model, ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve

REPO = Path(__file__).resolve().parents[2]
MODEL_DIR = REPO / "model"


@cache
def repo_models() -> dict[str, Model]:
    """``load_dir(model/)``, once per process."""
    return load_dir(MODEL_DIR)


@cache
def repo_resolved() -> ResolvedModels:
    """``resolve`` of ``repo_models()``, once per process."""
    return resolve(repo_models())


__all__ = ["MODEL_DIR", "REPO", "repo_models", "repo_resolved"]
