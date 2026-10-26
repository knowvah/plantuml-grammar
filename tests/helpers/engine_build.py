"""Build ``packages/engine`` once, even when pytest-xdist workers want it at the same time.

``tools.validate.ts_engine.ensure_built`` builds when ``dist/cli.js`` is older than the
sources. Two workers reaching that point together would run ``tsc`` into the same
``dist/`` at once, so the build runs under a file lock: the first worker builds, the
others wait, see a fresh ``dist/`` and skip.
"""

from __future__ import annotations

import fcntl
import hashlib
import tempfile
from pathlib import Path

from tools.validate import ts_engine

LOCK_PATH = Path(tempfile.gettempdir()) / (
    "plantuml-grammar-engine-build-"
    + hashlib.sha256(str(ts_engine.REPO_ROOT).encode()).hexdigest()[:12]
    + ".lock"
)


def build_engine_once() -> Path:
    """``packages/engine/dist`` with a current build; safe to call from several processes."""
    with LOCK_PATH.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            ts_engine.ensure_built()
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    return ts_engine.CLI_JS.parent


__all__ = ["LOCK_PATH", "build_engine_once"]
