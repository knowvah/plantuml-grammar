import pytest

from tools.translate.provenance import (
    ProvenanceError,
    ProvenanceIndex,
    find_line,
    git_reader,
    lookup,
    source_path,
)

CLASS = "net.sourceforge.plantuml.classdiagram.command.CommandCreateClass"
SOURCE = """package x;
// RegexConcat.build( in a comment
public class CommandCreateClass {
	CommandCreateClass() { super(getRegexConcat()); }
	private static IRegex getRegexConcat() {
		return RegexConcat.build("k");
	}
}
"""


def test_source_path_maps_nested_to_outer() -> None:
    assert source_path(CLASS) == (
        "src/main/java/net/sourceforge/plantuml/classdiagram/command/CommandCreateClass.java"
    )
    assert source_path("a.b.Outer$2").endswith("a/b/Outer.java")


def test_find_line_prefers_get_regex_concat() -> None:
    assert find_line(SOURCE, CLASS) == 5


def test_find_line_falls_back_to_build_then_class() -> None:
    assert find_line('class A {\n  X x = Pattern2.cmpile("a");\n}', "p.A") == 2
    assert find_line("// c\npublic final class A {\n}", "p.A") == 2


def test_find_line_without_anything_raises() -> None:
    with pytest.raises(ProvenanceError, match="p.B"):
        find_line("class A {}", "p.B")


def test_find_line_anonymous_counts_in_source_order() -> None:
    src = (
        'class N {\n  Object a = new Foo<X>(\n    "s)", 1) {\n  };\n'
        "  Object b = new Bar(1);\n  Object c = new Baz<Y>(f(2)) {\n  };\n}\n"
    )
    assert find_line(src, "p.N$1") == 2
    assert find_line(src, "p.N$2") == 6
    # Index beyond the anonymous classes falls through to the class declaration.
    assert find_line(src, "p.N$3") == 1


def test_index_caches_reads_per_path() -> None:
    calls: list[str] = []

    def reader(path: str) -> str:
        calls.append(path)
        return SOURCE

    index = ProvenanceIndex(reader)
    first = index.lookup(CLASS)
    assert (first.file.endswith("CommandCreateClass.java"), first.line) == (True, 5)
    assert index.lookup(CLASS) is first
    index.lookup(CLASS + "$1")
    assert len(calls) == 1


def test_lookup_one_shot() -> None:
    assert lookup(CLASS, lambda _: SOURCE).line == 5


def test_git_reader_reports_failure(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import subprocess

    from tools import config

    monkeypatch.setattr(config, "require", lambda name: tmp_path)
    ok = subprocess.CompletedProcess([], 0, stdout="text", stderr="")
    bad = subprocess.CompletedProcess([], 128, stdout="", stderr="fatal: bad")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: ok)
    assert git_reader("sha")("p") == "text"
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: bad)
    with pytest.raises(ProvenanceError, match="fatal: bad"):
        git_reader("sha")("p")
