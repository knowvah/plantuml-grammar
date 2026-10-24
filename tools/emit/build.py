"""Build ``dist/`` grammars from ``model/``: ``python -m tools.emit.build [--only a,b]``.

Each emitter is a function ``(ResolvedModels) -> str`` plus an output filename. To add
one, add a single line to ``EMITTERS`` naming it as ``"module:function"`` (imported
lazily, so a missing emitter module only fails when selected).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path

from tools.emit.engine import EngineBuildError
from tools.model import ModelLoadError, ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import resolve

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "model"
DIST_DIR = ROOT / "dist"
EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
ENCODING = "utf-8"


@dataclass(frozen=True)
class EmitterSpec:
    """An emitter reference (``module:function``) and the file it produces in dist."""

    target: str
    filename: str
    check: str | None = None

    def verify(self, path: Path) -> None:
        """Run the post-write check (``module:function`` taking the path), if any."""
        if self.check is not None:
            module, _, function = self.check.partition(":")
            getattr(import_module(module), function)(path)

    def render(self, resolved: ResolvedModels) -> str:
        module, _, function = self.target.partition(":")
        emit: Callable[[ResolvedModels], str] = getattr(import_module(module), function)
        return emit(resolved)


EMITTERS: dict[str, EmitterSpec] = {
    "textmate": EmitterSpec("tools.emit.textmate:emit_textmate_json", "plantuml.tmLanguage.json"),
    "engine": EmitterSpec(
        "tools.emit.engine:emit_engine_json",
        "plantuml.engine.json",
        "tools.emit.engine:report_engine",
    ),
}


def select(only: str | None) -> list[str]:
    """Emitter names to run; ``only`` is a comma list. Raises ``KeyError`` on unknown."""
    if only is None:
        return list(EMITTERS)
    names = [n.strip() for n in only.split(",") if n.strip()]
    unknown = [n for n in names if n not in EMITTERS]
    if unknown:
        raise KeyError(", ".join(unknown))
    return names


def build(names: Sequence[str], model_dir: Path, out_dir: Path) -> list[Path]:
    """Load + resolve ``model_dir`` and write each named emitter's file to ``out_dir``."""
    resolved = resolve(load_dir(model_dir))
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name in names:
        spec = EMITTERS[name]
        path = out_dir / spec.filename
        path.write_text(spec.render(resolved), encoding=ENCODING, newline="\n")
        spec.verify(path)
        written.append(path)
    return written


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    parser = argparse.ArgumentParser(prog="python -m tools.emit.build")
    parser.add_argument("--only", help="comma list of emitters: " + ",".join(EMITTERS))
    parser.add_argument("--model-dir", type=Path, default=MODEL_DIR)
    parser.add_argument("--out-dir", type=Path, default=DIST_DIR)
    args = parser.parse_args(argv)
    try:
        names = select(args.only)
    except KeyError as exc:
        print(f"unknown emitter: {exc.args[0]}", file=sys.stderr)
        return EXIT_USAGE
    try:
        written = build(names, args.model_dir, args.out_dir)
    except (ModelLoadError, EngineBuildError) as exc:
        print(exc, file=sys.stderr)
        return EXIT_ERROR
    for path in written:
        print(path)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
