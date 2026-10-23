from pathlib import Path

from tools.extract import build


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("class X {}\n")
    return path


def test_no_sources_exits_zero_with_notice(tmp_path, capsys):
    assert build.main(tmp_path, run=lambda cmd: 99) == 0
    assert "nothing to compile" in capsys.readouterr().out


def test_java_sources_collects_both_dirs_sorted(tmp_path):
    b = _touch(tmp_path / "tools/oracle/Oracle.java")
    a = _touch(tmp_path / "tools/extract/Extract.java")
    _touch(tmp_path / "tools/other/Ignored.java")
    assert build.java_sources(tmp_path) == [a, b]


def test_javac_command_shape():
    cmd = build.javac_command(Path("/j.jar"), [Path("/a.java")], Path("/out"))
    assert cmd == ["javac", "-cp", "/j.jar", "-d", "/out", "/a.java"]


def test_compiles_with_jar_into_build_java(tmp_path, monkeypatch):
    src = _touch(tmp_path / "tools/extract/Extract.java")
    jar = tmp_path / "p.jar"
    jar.write_bytes(b"")
    monkeypatch.setenv("PLANTUML_JAR", str(jar))
    seen: list[list[str]] = []
    assert build.main(tmp_path, run=lambda cmd: seen.append(cmd) or 0) == 0
    out = tmp_path / "build/java"
    assert out.is_dir()
    assert seen == [["javac", "-cp", str(jar), "-d", str(out), str(src)]]


def test_missing_jar_returns_2(tmp_path, monkeypatch, capsys):
    _touch(tmp_path / "tools/oracle/Oracle.java")
    monkeypatch.setenv("PLANTUML_JAR", str(tmp_path / "missing.jar"))
    assert build.main(tmp_path, run=lambda cmd: 0) == 2
    assert "PLANTUML_JAR not found" in capsys.readouterr().err
