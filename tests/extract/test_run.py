import json
from pathlib import Path

from tools.extract import run

PIN = {"sha": "abc123", "version": "9.9"}


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "upstream-pin.json").write_text(json.dumps(PIN))
    return tmp_path


def _jar(tmp_path: Path, monkeypatch) -> Path:
    jar = tmp_path / "p.jar"
    jar.write_bytes(b"")
    monkeypatch.setenv("PLANTUML_JAR", str(jar))
    return jar


def test_load_pin_reads_sha_and_version(tmp_path):
    assert run.load_pin(_repo(tmp_path)) == PIN


def test_java_command_passes_pin_classpath_and_out_dir():
    cmd = run.java_command(Path("/j.jar"), Path("/b"), Path("/o"), PIN)
    assert cmd == [
        "java",
        "-Dpin.sha=abc123",
        "-Dpin.version=9.9",
        "-cp",
        "/j.jar:/b",
        "Extract",
        "/o",
    ]


def test_build_failure_status_is_returned_and_extractor_not_run(tmp_path):
    seen: list[list[str]] = []
    status = run.run_extractor(
        _repo(tmp_path), compile_java=lambda: 7, run=lambda cmd: seen.append(cmd) or 0
    )
    assert status == 7
    assert seen == []


def test_missing_jar_exits_2_with_message(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PLANTUML_JAR", str(tmp_path / "absent.jar"))
    status = run.run_extractor(_repo(tmp_path), compile_java=lambda: 0, run=lambda cmd: 0)
    assert status == 2
    assert "PLANTUML_JAR not found" in capsys.readouterr().err


def test_default_output_dir_is_extracted_under_root(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    jar = _jar(tmp_path, monkeypatch)
    seen: list[list[str]] = []
    status = run.run_extractor(root, compile_java=lambda: 0, run=lambda cmd: seen.append(cmd) or 5)
    assert status == 5
    assert seen == [run.java_command(jar, root / "build/java", root / "extracted", PIN)]


def test_explicit_output_dir_overrides_default(tmp_path, monkeypatch):
    root = _repo(tmp_path)
    jar = _jar(tmp_path, monkeypatch)
    seen: list[list[str]] = []
    out = tmp_path / "elsewhere"
    run.run_extractor(root, out=out, compile_java=lambda: 0, run=lambda cmd: seen.append(cmd) or 0)
    assert seen[0][-1] == str(out)
    assert seen[0][4] == f"{jar}:{root / 'build/java'}"


def test_default_compile_uses_build_main(tmp_path, monkeypatch):
    # No Java sources under tmp_path: build.main prints a notice and returns 0.
    root = _repo(tmp_path)
    _jar(tmp_path, monkeypatch)
    seen: list[list[str]] = []
    assert run.run_extractor(root, run=lambda cmd: seen.append(cmd) or 0) == 0
    assert len(seen) == 1


def test_parse_args_out_option_and_default():
    assert run.parse_args(["--out", "/x"]).out == Path("/x")
    assert run.parse_args([]).out is None


def test_main_forwards_out_to_run_extractor(monkeypatch):
    got: dict = {}
    monkeypatch.setattr(run, "run_extractor", lambda out=None: got.update(out=out) or 3)
    assert run.main(["--out", "/x"]) == 3
    assert got == {"out": Path("/x")}
