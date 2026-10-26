"""Register the shared emit fixtures once, here, so test modules do not need
``pytest_plugins`` (which re-imports ``engine_support`` and defeats assertion rewriting)."""

from __future__ import annotations

from tests.emit.engine_support import built, engine_dist, engine_file, resolved

__all__ = ["built", "engine_dist", "engine_file", "resolved"]
