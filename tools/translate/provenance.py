"""Class FQCN to source file and the line that builds its regex, at the pinned sha.

``lookup`` reads ``src/main/java/<path>`` at 97a5992 through an injectable reader (the
default shells out to ``git -C $PLANTUML_SRC show``) and caches results in-process.
"""

from __future__ import annotations

import re
import subprocess  # nosec B404 - fixed argv, no shell
from collections.abc import Callable
from dataclasses import dataclass

from tools import config

SOURCE_ROOT = "src/main/java"
JAVA_SUFFIX = ".java"
NESTED_SEPARATOR = "$"

SourceReader = Callable[[str], str]

# Declaration of the method that builds the regex (RegexConcat or IRegex return type).
_REGEX_METHOD = re.compile(
    r"^\s*(?:(?:public|private|protected|static|final)\s+)*(?:RegexConcat|IRegex)\s+"
    r"getRegexConcat\s*\("
)
# First line that builds a regex when there is no such method (field/constructor).
_REGEX_BUILD = re.compile(
    r"RegexConcat\.build\(|new RegexConcat\(|Pattern2\.cmpile\(|Pattern\.compile\("
)
# Start of `new Foo<...>(`; an anonymous class when the matching `)` is followed by `{`.
_NEW_CALL = re.compile(r"\bnew\s+[\w.]+(?:<[^;{}()]*>)?\s*\(")
_STRING = re.compile(r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'')
_COMMENT = re.compile(r"^\s*(?://|\*|/\*)")


class ProvenanceError(Exception):
    """The upstream source of a class could not be read or located."""


@dataclass(frozen=True)
class Provenance:
    """Where a command's regex is built: path under the repo root and 1-based line."""

    file: str
    line: int


def source_path(fqcn: str) -> str:
    """Path of the file declaring ``fqcn`` (nested/anonymous map to the outer class)."""
    outer = fqcn.split(NESTED_SEPARATOR)[0]
    return f"{SOURCE_ROOT}/{outer.replace('.', '/')}{JAVA_SUFFIX}"


def _code_lines(source: str) -> list[tuple[int, str]]:
    return [
        (n, text) for n, text in enumerate(source.splitlines(), start=1) if not _COMMENT.match(text)
    ]


def _after_call(code: str, open_paren: int) -> str:
    """Text following the ``)`` that closes the ``(`` at ``open_paren`` (string-aware)."""
    depth = 0
    for m in re.finditer(r"[()]", _STRING.sub(lambda x: " " * len(x.group()), code[open_paren:])):
        depth += 1 if m.group() == "(" else -1
        if depth == 0:
            return code[open_paren + m.end() :].lstrip()
    return ""


def _anonymous_line(source: str, index: int) -> int | None:
    """Line of the ``index``-th (1-based) anonymous class body, in source order."""
    code = "\n".join("" if _COMMENT.match(t) else t for t in source.splitlines())
    hits = [
        code.count("\n", 0, m.start()) + 1
        for m in _NEW_CALL.finditer(code)
        if _after_call(code, m.end() - 1).startswith("{")
    ]
    return hits[index - 1] if 0 < index <= len(hits) else None


def find_line(source: str, fqcn: str) -> int:
    """1-based line of the code that builds ``fqcn``'s regex.

    Order: `getRegexConcat` declaration; for an anonymous ``Outer$N`` the Nth anonymous
    class body; first `RegexConcat.build`/`Pattern2.cmpile` line; the class declaration.
    """
    lines = _code_lines(source)
    suffix = fqcn.split(NESTED_SEPARATOR, 1)[1] if NESTED_SEPARATOR in fqcn else ""
    if suffix.isdigit():
        anon = _anonymous_line(source, int(suffix))
        if anon is not None:
            return anon
    for pattern in (_REGEX_METHOD, _REGEX_BUILD):
        for number, text in lines:
            if pattern.search(text):
                return number
    simple = fqcn.split(".")[-1].split(NESTED_SEPARATOR)[0]
    decl = re.compile(rf"\b(?:class|interface|enum)\s+{re.escape(simple)}\b")
    for number, text in lines:
        if decl.search(text):
            return number
    raise ProvenanceError(f"no regex-building code found for {fqcn}")


def git_reader(sha: str = config.PIN_SHA) -> SourceReader:
    """Reader that returns a file's text at ``sha`` from the upstream checkout."""

    def read(path: str) -> str:
        src = config.require("src")
        result = subprocess.run(  # nosec B603 B607 - fixed argv, no shell
            ["git", "-C", str(src), "show", f"{sha}:{path}"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise ProvenanceError(f"cannot read {path} at {sha}: {result.stderr.strip()}")
        return result.stdout

    return read


class ProvenanceIndex:
    """In-process cache of ``Provenance`` per FQCN over an injected source reader."""

    def __init__(self, reader: SourceReader | None = None) -> None:
        self._reader = reader or git_reader()
        self._sources: dict[str, str] = {}
        self._results: dict[str, Provenance] = {}

    def lookup(self, fqcn: str) -> Provenance:
        """Provenance of ``fqcn``; the file is read at most once per path."""
        if fqcn not in self._results:
            path = source_path(fqcn)
            if path not in self._sources:
                self._sources[path] = self._reader(path)
            self._results[fqcn] = Provenance(path, find_line(self._sources[path], fqcn))
        return self._results[fqcn]


def lookup(fqcn: str, reader: SourceReader | None = None) -> Provenance:
    """One-shot ``Provenance`` for ``fqcn`` (use ``ProvenanceIndex`` to cache across calls)."""
    return ProvenanceIndex(reader).lookup(fqcn)
