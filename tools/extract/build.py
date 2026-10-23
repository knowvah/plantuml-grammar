"""Compile the Java extractor and oracle harness against the pinned jar.

Usage: python -m tools.extract.build
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from tools.config import ConfigError, require

REPO_ROOT = Path(__file__).resolve().parents[2]
JAVA_DIRS = ("tools/extract", "tools/oracle")
OUT_DIR = "build/java"


def java_sources(root: Path) -> list[Path]:
    return sorted(p for d in JAVA_DIRS for p in (root / d).glob("*.java"))


def javac_command(jar: Path, sources: Sequence[Path], out: Path) -> list[str]:
    return ["javac", "-cp", str(jar), "-d", str(out), *map(str, sources)]


def main(
    root: Path = REPO_ROOT,
    run: Callable[[list[str]], int] = lambda cmd: subprocess.call(cmd),
) -> int:
    sources = java_sources(root)
    if not sources:
        print("no Java sources under tools/extract or tools/oracle; nothing to compile")
        return 0
    try:
        jar = require("jar")
    except ConfigError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    out = root / OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    return run(javac_command(jar, sources, out))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
