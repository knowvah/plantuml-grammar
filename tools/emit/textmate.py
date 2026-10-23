"""Emit the command model as a TextMate grammar, ``dist/plantuml.tmLanguage.json``.

Shape (scope name ``source.plantuml``)::

    patterns: one begin/end block per ``@start<kw>`` keyword
    repository:
      comments, preprocessor      fixed rules, included in every block
      diagram_<kw>                union of the main contexts of the diagram models that
                                  share ``@start<kw>`` (identical rules deduplicated)
      ctx_<model>_<context>       a pushed context (one entry per push/set target)

Mapping from model entries:

* ``single`` / ``opaque`` -> ``match`` with the flattened regex; a Part's ``scope``
  becomes a numbered capture (``<scope>.plantuml``), unscoped Parts do not capture.
* ``multiline`` / ``multiline-bracket`` -> ``begin``/``end`` (the entry's ``end`` Part)
  with the pushed context, if any, as nested patterns.
* a ``single`` entry with ``push``/``set`` -> ``begin``/``end`` where ``end`` is the
  alternation of the pushed context's ``pop`` entries (``$`` if it has none).
* a multiline entry without ``end`` (the generated models omit it) ends at ``^\\s*\\}`` for
  ``multiline-bracket`` and at the end of the first line otherwise.
* a ``multiline`` entry with ``join`` is approximated as a single-line ``match`` of its
  ``parts`` (upstream re-matches up to ``max_lines`` + 1 lines joined with U+E100).
* a regex Part with ``ci: true`` is wrapped in ``(?i:...)`` (supported by Oniguruma and
  PCRE2); absent ``ci`` stays case-sensitive.
* ``pop`` entries are ordinary ``match`` rules outside a pushed context.

A rule whose ``match`` / ``begin`` regex can match the empty string is NOT emitted
(``textmate_regex.can_match_empty``). Oniguruma finds a zero-length match at column 0 of every
line, earlier than any real rule, and vscode-textmate takes it: common's ``CommandNope``
(``[\\s\\xa0]*``) otherwise left every body line of every command factory unscoped. TextMate
has no assertion that forces a non-empty match, so such rules (blank-line rules and
catch-alls like ``.*``) lose their scope; ``end`` regexes (``$``) are zero-width on purpose
and are not filtered.

Context transitions are only approximated (TextMate has no frame replacement):

* ``set`` nests the target's region inside the current one exactly like ``push``, so after
  an if/else the enclosing region stays open until its own ``pop`` line (highlighting
  only; the interpreter replaces the frame).
* ``require_pop`` is ignored: an unclosed region simply extends to the end of the block.
* The ``end`` of a region is the alternation of the target's ``pop`` entries. The flattened
  regexes are searched anywhere in the line and only carry ``^``/``$`` where a model regex
  has them, so indentation and trailing blanks do not stop a match (no whitespace
  handling is added).

Approximation: TextMate is line based and picks the leftmost-first rule of the active
list, so upstream's ordered, stateful command matching is only approximated.

Contract keys ignored by this emitter: ``gives``/``needs`` (diagram flags, final-state
checks) are ignored; ``trim: false`` is ignored (the emitted pattern is matched against
the trimmed line); ``emit: false`` entries are dropped like ``reject`` (see ``skip.py``).

Regex dialect: patterns keep the model's Java text; TextMate/Oniguruma is its own engine and is
not routed through ``tools.model.java_regex``.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from tools.emit.keywords import (
    END_DIRECTIVE,
    START_DIRECTIVE,
    document_start_map,
    group_by_keyword,
    uncovered_lookahead,
)
from tools.emit.skip import skipped
from tools.emit.textmate_regex import Captures, can_match_empty, flatten, flatten_alternatives
from tools.model import Entry, ModelLoadError, ResolvedModel, ResolvedModels
from tools.model.load import load_dir
from tools.model.resolve import MAIN_CONTEXT, resolve

SCOPE_NAME = "source.plantuml"
FILE_TYPES = ["puml", "plantuml", "pu", "iuml", "wsd"]
MULTILINE_KINDS = frozenset({"multiline", "multiline-bracket"})
LINE_END = "$"
JOIN_KEY = "join"
BRACKET_KIND = "multiline-bracket"
BRACKET_END = "^\\s*\\}"
ENCODING = "utf-8"
EXIT_OK = 0
EXIT_ERROR = 1
COMMENTS = "comments"
PREPROCESSOR = "preprocessor"
BLOCK_SCOPE = "meta.diagram.plantuml"
START_SCOPE = "keyword.control.start.plantuml"
END_SCOPE = "keyword.control.end.plantuml"
Rule = dict[str, Any]

COMMENT_RULES: Rule = {
    "patterns": [
        {
            "name": "comment.block.plantuml",
            "begin": "/'",
            "end": "'/",
        },
        {"name": "comment.line.apostrophe.plantuml", "match": "^\\s*'.*$"},
    ]
}
PREPROCESSOR_RULES: Rule = {
    "patterns": [
        {
            "name": "meta.preprocessor.plantuml",
            "match": "^\\s*(![A-Za-z_]\\w*).*$",
            "captures": {"1": {"name": "keyword.control.directive.plantuml"}},
        }
    ]
}


def _with_captures(rule: Rule, key: str, captures: Captures) -> Rule:
    if captures:
        rule[key] = captures
    return rule


def _ctx_key(model: ResolvedModel, context: str) -> str:
    return f"ctx_{model.id}_{context}"


class _Rules:
    """Turns entries of one model into TextMate rules, collecting pushed contexts."""

    def __init__(self, model: ResolvedModel, repository: dict[str, Rule]) -> None:
        self.model = model
        self.repository = repository

    def context_rules(self, entries: list[Entry], skip_pop: bool) -> list[Rule]:
        """Rules for ``entries``; ``skip_pop`` leaves ``pop`` entries to the ``end``."""
        rules = []
        for entry in entries:
            if "command" not in entry or skipped(entry) or (skip_pop and entry.get("pop")):
                continue
            rule = self.entry_rule(entry)
            if not can_match_empty(rule.get("match") or rule["begin"]):
                rules.append(rule)
        return rules

    def entry_rule(self, entry: Entry) -> Rule:
        """One rule for a command entry."""
        regex, captures = flatten(entry["parts"])
        target = entry.get("push") or entry.get("set")
        if entry["kind"] in MULTILINE_KINDS and JOIN_KEY not in entry:
            end_regex, end_captures = self._multiline_end(entry)
        elif target in self.model.contexts:
            end_regex, end_captures = self._pop_end(target)
        else:
            return _with_captures({"match": regex}, "captures", captures)
        rule: Rule = {"begin": regex}
        _with_captures(rule, "beginCaptures", captures)
        rule["end"] = end_regex
        _with_captures(rule, "endCaptures", end_captures)
        if target in self.model.contexts:
            rule["patterns"] = [{"include": "#" + self._push(target)}]
        return rule

    @staticmethod
    def _multiline_end(entry: Entry) -> tuple[str, Captures]:
        if "end" in entry:
            return flatten(entry["end"])
        if entry["kind"] == BRACKET_KIND:
            return BRACKET_END, {}
        return LINE_END, {}

    def _pop_end(self, context: str) -> tuple[str, Captures]:
        pops = [e["parts"] for e in self.model.contexts[context] if e.get("pop") and not skipped(e)]
        return flatten_alternatives(pops) if pops else (LINE_END, {})

    def _push(self, context: str) -> str:
        key = _ctx_key(self.model, context)
        if key not in self.repository:
            self.repository[key] = {"patterns": []}  # reserve first: contexts may recurse
            patterns = self.context_rules(self.model.contexts[context], skip_pop=True)
            self.repository[key]["patterns"] = patterns
        return key


def _group_rules(models: list[ResolvedModel], repository: dict[str, Rule]) -> list[Rule]:
    """Union of the main-context rules of ``models``, identical rules kept once."""
    seen: set[str] = set()
    rules: list[Rule] = []
    for model in models:
        builder = _Rules(model, repository)
        for rule in builder.context_rules(model.contexts.get(MAIN_CONTEXT, []), False):
            key = json.dumps(rule, sort_keys=True)
            if key not in seen:
                seen.add(key)
                rules.append(rule)
    return rules


def _framed(start: str, patterns: list[Rule]) -> Rule:
    return {
        "name": BLOCK_SCOPE,
        "begin": f"^\\s*({start})",
        "beginCaptures": {"1": {"name": START_SCOPE}},
        "end": f"^\\s*({END_DIRECTIVE}[A-Za-z0-9]*)",
        "endCaptures": {"1": {"name": END_SCOPE}},
        "patterns": [{"include": "#" + COMMENTS}, {"include": "#" + PREPROCESSOR}, *patterns],
    }


def _block(keyword: str) -> Rule:
    return _framed(f"{START_DIRECTIVE}{_fold(keyword)}", [{"include": f"#diagram_{keyword}"}])


def _other_block(keywords: Sequence[str]) -> Rule:
    """A start word no keyword covers: PSystemUnsupported, any body (see keywords.py)."""
    # At least one character must follow `start` (StartUtils.isStartDirective).
    other = uncovered_lookahead(keywords, _fold)
    return _framed(f"{START_DIRECTIVE}{other}(?=[^\\r\\n])\\S*", [])


def _fold(keyword: str) -> str:
    """The keyword folds case, ``start`` does not (see keywords.py). Oniguruma's ``(?i:...)``
    also folds non-ASCII letters; a highlighting approximation."""
    return f"(?i:{keyword})"


def emit_textmate(resolved: ResolvedModels) -> dict[str, Any]:
    """The tmLanguage grammar for the diagram-layer models in ``resolved``."""
    repository: dict[str, Rule] = {
        COMMENTS: COMMENT_RULES,
        PREPROCESSOR: PREPROCESSOR_RULES,
    }
    groups = group_by_keyword(resolved)
    blocks = []
    for keyword, models in groups.items():
        repository[f"diagram_{keyword}"] = {"patterns": _group_rules(models, repository)}
        blocks.append(_block(keyword))
    if groups:  # with no keyword the exclusion `(?!(?:))` never matches; emit no block
        blocks.append(_other_block([*document_start_map(resolved), *groups]))
    return {
        "name": "PlantUML",
        "scopeName": SCOPE_NAME,
        "fileTypes": FILE_TYPES,
        "patterns": [{"include": "#" + COMMENTS}, *blocks],
        "repository": repository,
    }


def emit_textmate_json(resolved: ResolvedModels) -> str:
    """Registry-compatible emitter: the grammar as 2-space-indented JSON + newline."""
    return json.dumps(emit_textmate(resolved), indent=2, ensure_ascii=False) + "\n"


def regexes(grammar: Any) -> list[str]:
    """Every ``match``/``begin``/``end`` regex anywhere in ``grammar``, in document order."""
    found: list[str] = []
    if isinstance(grammar, dict):
        for key, value in grammar.items():
            if key in ("match", "begin", "end") and isinstance(value, str):
                found.append(value)
            else:
                found.extend(regexes(value))
    elif isinstance(grammar, list):
        for item in grammar:
            found.extend(regexes(item))
    return found


def main(argv: Sequence[str] | None = None) -> int:
    """``python -m tools.emit.textmate --model-dir DIR --out FILE``."""
    parser = argparse.ArgumentParser(prog="python -m tools.emit.textmate")
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        text = emit_textmate_json(resolve(load_dir(args.model_dir)))
    except ModelLoadError as exc:
        print(exc, file=sys.stderr)
        return EXIT_ERROR
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding=ENCODING, newline="\n")
    print(args.out)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
