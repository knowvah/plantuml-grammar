"""Load and validate command-model YAML files (contract I2).

CLI: ``python -m tools.model.load --check <dir>`` exits non-zero on any error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterator, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

import regex
import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from tools.model import Model, ModelError, ModelLoadError, Part
from tools.model.patch import (
    INSERT_AFTER,
    INSERT_BEFORE,
    OVERRIDES,
    SCHEMA_PATH,
)
from tools.model.resolve import LIST_KEYS, UNARY_KEYS, resolve

MODEL_GLOB = "*.yaml"
# Upstream Pattern2 macro table, regex/Pattern2.java:54-59 and TRANSFORM_PATTERN at :62.
UPSTREAM_MACRO = re.compile(r"%(?:pLN|s|q|g)")
# A `\uXXXX` escape: an odd number of backslashes before `u` (`\\u` is a literal backslash).
UNICODE_ESCAPE = re.compile(r"(?<!\\)(?:\\\\)*\\u")
UNICODE_ESCAPE_HINT = (
    "\\u escape in regex: PCRE2 rejects it; write the character as a literal character "
    '(a YAML double-quoted "\\uE100" already yields the literal)'
)
EXIT_OK = 0
EXIT_ERRORS = 1


@lru_cache(maxsize=1)
def _validator() -> Draft202012Validator:
    return Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


def _pointer(parts: Sequence[object]) -> str:
    return "".join("/" + str(p).replace("~", "~0").replace("/", "~1") for p in parts)


def _leaves(error: ValidationError) -> list[ValidationError]:
    """Descend into oneOf/anyOf to the errors of the best-matching branch.

    The branch with the fewest errors wins (ties go to the earliest), so an unknown key
    in a command entry is reported against the command branch, not the include branch.
    """
    if not error.context:
        return [error]
    branches: dict[object, list[ValidationError]] = {}
    for sub in error.context:
        branches.setdefault(sub.relative_schema_path[0], []).append(sub)
    best = min(branches.values(), key=len)
    return [leaf for sub in best for leaf in _leaves(sub)]


def _schema_errors(doc: object, file: str) -> list[ModelError]:
    errors: list[ModelError] = []
    for raw in _validator().iter_errors(doc):
        for err in _leaves(raw):
            errors.extend(_to_model_errors(err, file))
    return errors


def _to_model_errors(err: ValidationError, file: str) -> list[ModelError]:
    base = list(err.absolute_path)
    if err.validator == "additionalProperties" and isinstance(err.instance, dict):
        allowed = err.schema.get("properties", {})
        return [
            ModelError("unknown key", file, _pointer([*base, key]))
            for key in err.instance
            if key not in allowed
        ]
    return [ModelError(err.message, file, _pointer(base))]


def iter_regexes(part: Part, pointer: str) -> Iterator[tuple[str, str]]:
    """Yield ``(json_pointer, pattern)`` for every regex Part nested in ``part``."""
    if "regex" in part:
        yield f"{pointer}/regex", part["regex"]
    for key in LIST_KEYS:
        for index, child in enumerate(part.get(key, [])):
            yield from iter_regexes(child, f"{pointer}/{key}/{index}")
    for key in UNARY_KEYS:
        if key in part:
            yield from iter_regexes(part[key], f"{pointer}/{key}")


def _entry_parts(entry: dict[str, Any], base: str) -> Iterator[tuple[str, Part]]:
    for key in ("parts", "end"):
        if isinstance(entry.get(key), dict):
            yield f"{base}/{key}", entry[key]


def _model_parts(doc: dict[str, Any]) -> Iterator[tuple[str, Part]]:
    for name, part in doc.get("variables", {}).items():
        yield f"/variables/{name}", part
    for cname, entries in doc.get("contexts", {}).items():
        for index, entry in enumerate(entries):
            yield from _entry_parts(entry, f"/contexts/{cname}/{index}")
    for key, patch in doc.get(OVERRIDES, {}).items():
        yield from _entry_parts(patch, f"/{OVERRIDES}/{key}")
    for section in (INSERT_BEFORE, INSERT_AFTER):
        for key, entries in doc.get(section, {}).items():
            for index, entry in enumerate(entries):
                yield from _entry_parts(entry, f"/{section}/{key}/{index}")


def check_pattern(pattern: str) -> str | None:
    """Return a problem description for ``pattern``, or None when it is acceptable.

    Compiled with the ``regex`` module (V0, a superset of ``re``) because expanded macros
    contain ``\\p{L}``/``\\p{N}``, which ``re`` rejects.
    """
    macro = UPSTREAM_MACRO.search(pattern)
    if macro:
        return f"unexpanded upstream macro '{macro.group()}'"
    if UNICODE_ESCAPE.search(pattern):
        return UNICODE_ESCAPE_HINT
    try:
        regex.compile(pattern)
    except regex.error as exc:
        return f"regex does not compile: {exc}"
    return None


def _regex_errors(doc: dict[str, Any], file: str) -> list[ModelError]:
    errors = []
    for pointer, part in _model_parts(doc):
        for ptr, pattern in iter_regexes(part, pointer):
            problem = check_pattern(pattern)
            if problem:
                errors.append(ModelError(problem, file, ptr))
    return errors


def parse_document(text: str, file: str) -> tuple[dict[str, Any] | None, list[ModelError]]:
    """Parse and validate one YAML document; return ``(doc, errors)``."""
    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return None, [ModelError(f"invalid YAML: {exc}", file)]
    errors = _schema_errors(doc, file)
    if errors:
        return None, errors
    errors = _regex_errors(doc, file)
    return (None, errors) if errors else (doc, [])


def _to_model(doc: dict[str, Any], path: Path) -> Model:
    return Model(
        id=doc["id"],
        layer=doc["layer"],
        path=path,
        diagram=doc.get("diagram"),
        include=list(doc.get("include", [])),
        variables=doc.get("variables", {}),
        contexts=doc.get("contexts", {}),
        factory=doc.get("factory"),
        start_map={k: list(v) for k, v in doc.get("start_map", {}).items()},
        empty_needs_end=bool(doc.get("empty_needs_end", False)),
        overrides=doc.get(OVERRIDES, {}),
        insert_before=doc.get(INSERT_BEFORE, {}),
        insert_after=doc.get(INSERT_AFTER, {}),
    )


def discover(root: Path) -> list[Path]:
    """All model files under ``root`` (recursive, sorted); ``schema.json`` is not YAML."""
    return sorted(root.rglob(MODEL_GLOB))


def _load_files(paths: list[Path]) -> tuple[dict[str, Model], list[ModelError]]:
    models: dict[str, Model] = {}
    errors: list[ModelError] = []
    for path in paths:
        doc, file_errors = parse_document(path.read_text(encoding="utf-8"), str(path))
        errors.extend(file_errors)
        if doc is None:
            continue
        if doc["id"] != path.stem:
            errors.append(
                ModelError(f"id '{doc['id']}' must equal file stem '{path.stem}'", str(path), "/id")
            )
        elif doc["id"] in models:
            other = models[doc["id"]].path
            errors.append(
                ModelError(f"duplicate id '{doc['id']}' (also {other})", str(path), "/id")
            )
        else:
            models[doc["id"]] = _to_model(doc, path)
    return models, errors


def load_dir(path: Path | str) -> dict[str, Model]:
    """Load every ``*.yaml`` under ``path`` recursively, keyed by model id.

    The id is the file stem and must be unique across the whole tree (including
    ``model/generated/``). Raises ``ModelLoadError`` listing all problems found:
    schema violations, unexpanded or uncompilable regexes, id/stem mismatches,
    duplicate ids, unknown ``include``/``ref`` targets and include cycles.
    """
    root = Path(path)
    if not root.is_dir():
        raise ModelLoadError([ModelError("not a directory", str(root))])
    models, errors = _load_files(discover(root))
    if not errors:
        try:
            resolve(models)
        except ModelError as exc:
            errors.append(exc)
    if errors:
        raise ModelLoadError(errors)
    return models


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point; returns the process exit code."""
    parser = argparse.ArgumentParser(prog="python -m tools.model.load")
    parser.add_argument("--check", metavar="DIR", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        models = load_dir(args.check)
    except ModelLoadError as exc:
        for error in exc.errors:
            print(error, file=sys.stderr)
        return EXIT_ERRORS
    print(f"ok: {len(models)} model(s)")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
