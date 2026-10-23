"""Build the Java extractor and run it, writing I1 raw extraction JSON.

Usage: python -m tools.extract.run [--out DIR]   (default DIR: extracted/)
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from tools.config import ConfigError, load_pin, require
from tools.extract import build

REPO_ROOT = build.REPO_ROOT
DEFAULT_OUT = "extracted"
MAIN_CLASS = "Extract"
EXIT_CONFIG = 2

Runner = Callable[[list[str]], int]


def java_command(jar: Path, classes: Path, out: Path, pin: dict[str, str]) -> list[str]:
    return [
        "java",
        f"-Dpin.sha={pin['sha']}",
        f"-Dpin.version={pin['version']}",
        "-cp",
        f"{jar}{os.pathsep}{classes}",
        MAIN_CLASS,
        str(out),
    ]


def run_extractor(
    root: Path = REPO_ROOT,
    out: Path | None = None,
    compile_java: Callable[[], int] | None = None,
    run: Runner = lambda cmd: subprocess.call(cmd),
) -> int:
    """Compile (unless `compile_java` is overridden) and run the extractor into `out`."""
    status = (compile_java or (lambda: build.main(root)))()
    if status != 0:
        return status
    try:
        jar = require("jar")
    except ConfigError as err:
        print(f"error: {err}", file=sys.stderr)
        return EXIT_CONFIG
    target = out if out is not None else root / DEFAULT_OUT
    return run(java_command(jar, root / build.OUT_DIR, target, load_pin(root)))


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract upstream command regex trees")
    parser.add_argument("--out", type=Path, default=None, help="output directory")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    return run_extractor(out=args.out)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
