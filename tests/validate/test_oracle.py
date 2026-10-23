import hashlib
import json
from pathlib import Path

import pytest

from tools.validate import oracle
from tools.validate.oracle import ORACLE_VERSION, OracleError, oracle_verdicts, preproc

FIXTURES = Path(__file__).parent / "fixtures"
PIN = "pin123"


def _block(index=0, accepted=True, line=None, lines=("@startuml", "@enduml")):
    return {
        "index": index,
        "start_keyword": "@startuml",
        "accepted": accepted,
        "diagram_type": "CLASS" if accepted else None,
        "error_line": line,
        "preproc": list(lines),
    }


class FakeJvm:
    """Injected runner: records batches and replays canned JSON lines."""

    def __init__(self, answers):
        self.answers = answers
        self.batches = []

    def __call__(self, paths):
        self.batches.append(list(paths))
        for p in paths:
            if p in self.answers:
                yield json.dumps(self.answers[p])


def _file(tmp_path, name, text="@startuml\nclass A\n@enduml\n"):
    p = tmp_path / name
    p.write_bytes(text.encode())
    return p


def _ok(path, *blocks):
    return {"path": str(path), "blocks": list(blocks) or [_block()]}


def test_cache_miss_goes_to_single_batch_and_is_returned(tmp_path):
    a, b = _file(tmp_path, "a.puml"), _file(tmp_path, "b.puml", "@startuml\nclass B\n@enduml\n")
    jvm = FakeJvm({str(a): _ok(a), str(b): _ok(b, _block(accepted=False, line=3))})

    out = oracle_verdicts([a, b], runner=jvm, cache_dir=tmp_path / "c", pin=PIN)

    assert jvm.batches == [[str(a), str(b)]]
    assert out[str(a)][0]["accepted"] is True
    assert out[str(b)][0]["accepted"] is False
    assert out[str(b)][0]["error_line"] == 3


def test_second_call_launches_no_jvm(tmp_path):
    a = _file(tmp_path, "a.puml")
    jvm = FakeJvm({str(a): _ok(a)})
    cache = tmp_path / "c"
    first = oracle_verdicts([a], runner=jvm, cache_dir=cache, pin=PIN)

    again = FakeJvm({})
    second = oracle_verdicts([a], runner=again, cache_dir=cache, pin=PIN)

    assert again.batches == []
    assert second == first


def test_only_misses_are_sent(tmp_path):
    a, b = _file(tmp_path, "a.puml"), _file(tmp_path, "b.puml", "@startuml\nclass B\n@enduml\n")
    cache = tmp_path / "c"
    oracle_verdicts([a], runner=FakeJvm({str(a): _ok(a)}), cache_dir=cache, pin=PIN)
    jvm = FakeJvm({str(b): _ok(b)})

    oracle_verdicts([a, b], runner=jvm, cache_dir=cache, pin=PIN)

    assert jvm.batches == [[str(b)]]


def test_cache_key_is_content_sha_pin_and_oracle_version(tmp_path):
    a = _file(tmp_path, "a.puml")
    cache = tmp_path / "c"
    oracle_verdicts([a], runner=FakeJvm({str(a): _ok(a)}), cache_dir=cache, pin=PIN)

    digest = hashlib.sha256(a.read_bytes()).hexdigest()
    assert [p.name for p in cache.iterdir()] == [f"{digest}-{PIN}-o{ORACLE_VERSION}.json"]


def test_content_change_or_pin_change_invalidates(tmp_path):
    a = _file(tmp_path, "a.puml")
    cache = tmp_path / "c"
    oracle_verdicts([a], runner=FakeJvm({str(a): _ok(a)}), cache_dir=cache, pin=PIN)

    other_pin = FakeJvm({str(a): _ok(a)})
    oracle_verdicts(
        [a],
        runner=other_pin,
        cache_dir=cache,
        pin="other",
    )
    assert other_pin.batches == [[str(a)]]

    a.write_bytes(b"@startuml\nclass Z\n@enduml\n")
    changed = FakeJvm({str(a): _ok(a)})
    oracle_verdicts([a], runner=changed, cache_dir=cache, pin=PIN)
    assert changed.batches == [[str(a)]]


def test_two_blocks_keep_indexes(tmp_path):
    a = _file(tmp_path, "a.puml")
    jvm = FakeJvm({str(a): _ok(a, _block(0), _block(1))})

    out = oracle_verdicts([a], runner=jvm, cache_dir=tmp_path / "c", pin=PIN)

    assert [v["index"] for v in out[str(a)]] == [0, 1]


def test_per_file_error_becomes_error_verdict_and_is_not_cached(tmp_path):
    a, b = _file(tmp_path, "a.puml"), _file(tmp_path, "b.puml", "@startuml\nclass B\n@enduml\n")
    jvm = FakeJvm(
        {str(a): {"path": str(a), "error": "java.lang.StackOverflowError"}, str(b): _ok(b)}
    )
    cache = tmp_path / "c"

    out = oracle_verdicts([a, b], runner=jvm, cache_dir=cache, pin=PIN)

    assert out[str(a)] == [
        {
            "index": 0,
            "start_keyword": "",
            "accepted": False,
            "diagram_type": None,
            "error_line": None,
            "preproc": [],
            "error": "java.lang.StackOverflowError",
        }
    ]
    assert out[str(b)][0]["accepted"] is True
    assert len(list(cache.iterdir())) == 1


def test_file_missing_from_jvm_output_is_error_verdict(tmp_path):
    a = _file(tmp_path, "a.puml")

    out = oracle_verdicts([a], runner=FakeJvm({}), cache_dir=tmp_path / "c", pin=PIN)

    assert out[str(a)][0]["accepted"] is False
    assert out[str(a)][0].get("error") == "no verdict returned by oracle JVM"


def test_summary_line_on_stderr(tmp_path, capsys):
    a, b = _file(tmp_path, "a.puml"), _file(tmp_path, "b.puml", "@startuml\nclass B\n@enduml\n")
    cache = tmp_path / "c"
    oracle_verdicts(
        [a], runner=FakeJvm({str(a): _ok(a, _block(0), _block(1))}), cache_dir=cache, pin=PIN
    )
    capsys.readouterr()

    oracle_verdicts([a, b], runner=FakeJvm({str(b): _ok(b)}), cache_dir=cache, pin=PIN)

    summary = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert summary["files"] == 2
    assert summary["blocks"] == 3
    assert summary["cache_hits"] == 1
    assert isinstance(summary["jvm_seconds"], float)


def test_no_misses_means_no_runner_call_even_for_empty_input(tmp_path):
    jvm = FakeJvm({})
    assert oracle_verdicts([], runner=jvm, cache_dir=tmp_path / "c", pin=PIN) == {}
    assert jvm.batches == []


def test_preproc_reads_block_lines_from_cache(tmp_path):
    a = _file(tmp_path, "a.puml")
    lines = ("@startuml", "class Foo", "@enduml")
    jvm = FakeJvm({str(a): _ok(a, _block(0, lines=lines))})

    got = preproc(a, 0, runner=jvm, cache_dir=tmp_path / "c", pin=PIN)

    assert got == list(lines)


def test_default_pin_comes_from_upstream_pin_json():
    pin = json.loads((Path(__file__).parents[2] / "upstream-pin.json").read_text())["sha"]
    assert oracle.default_pin() == pin


def test_parse_line_rejects_garbage():
    with pytest.raises(OracleError, match="not JSON"):
        oracle.parse_line("oops")


def test_jvm_command_uses_build_dir_and_jar(tmp_path):
    cmd = oracle.jvm_command(tmp_path / "x.jar", tmp_path / "build")
    assert cmd == ["java", "-cp", f"{tmp_path / 'build'}:{tmp_path / 'x.jar'}", "Oracle"]


def test_missing_oracle_class_has_actionable_message(tmp_path):
    with pytest.raises(OracleError, match=r"python -m tools\.extract\.build"):
        oracle.ensure_built(tmp_path)


def test_ensure_built_passes_when_class_exists(tmp_path):
    (tmp_path / "Oracle.class").write_bytes(b"")
    oracle.ensure_built(tmp_path)


def test_jvm_runner_streams_lines_and_checks_exit(tmp_path):
    seen = {}

    def fake_popen(cmd, stdin, stdout, stderr, text):
        seen["stdin"] = stdin.read()

        class P:
            def __init__(self):
                self.stdout = iter(['{"path":"x"}\n', '{"path":"y"}\n'])
                self.returncode = 0

            def wait(self):
                return 0

        return P()

    run = oracle.make_jvm_runner(["java"], popen=fake_popen)

    assert list(run(["p1", "p2"])) == ['{"path":"x"}', '{"path":"y"}']
    assert seen["stdin"] == "p1\np2\n"


def test_jvm_runner_raises_on_nonzero_exit():
    def fake_popen(cmd, stdin, stdout, stderr, text):
        class P:
            stdout = iter([])
            returncode = 1

            def wait(self):
                return 1

        return P()

    with pytest.raises(OracleError, match="exited with 1"):
        list(oracle.make_jvm_runner(["java"], popen=fake_popen)(["p"]))


@pytest.mark.corpus
def test_real_jvm_fixtures(tmp_path):
    out = oracle_verdicts(sorted(FIXTURES.glob("*.puml")), cache_dir=tmp_path)
    by = {Path(k).name: v for k, v in out.items()}
    assert by["good.puml"][0]["accepted"] is True
    assert by["good.puml"][0]["diagram_type"] == "CLASS"
    assert by["bad.puml"][0]["accepted"] is False
    assert by["bad.puml"][0]["error_line"] is not None
    assert [v["index"] for v in by["two_blocks.puml"]] == [0, 1]
    assert "class Foo" in by["define.puml"][0]["preproc"]
    assert "---" not in by["yaml_header.puml"][0]["preproc"]
    assert by["yaml_bad.puml"][0]["error_line"] == 5


@pytest.mark.corpus
def test_relative_include_resolves_against_the_source_file(tmp_path):
    """Mirrors SourceFileReader.java:79: !include is relative to the file, not the JVM cwd."""
    source = FIXTURES / "incdir" / "include_rel.puml"
    [verdict] = oracle_verdicts([source], cache_dir=tmp_path)[str(source)]
    assert verdict["accepted"] is True
    assert "class Inc" in verdict["preproc"]


def test_zero_block_file_is_cached_as_empty_list(tmp_path):
    a = _file(tmp_path, "a.puml", "no blocks here\n")
    cache = tmp_path / "c"
    first = oracle_verdicts(
        [a], runner=FakeJvm({str(a): {"path": str(a), "blocks": []}}), cache_dir=cache, pin=PIN
    )
    again = FakeJvm({})

    second = oracle_verdicts([a], runner=again, cache_dir=cache, pin=PIN)

    assert first[str(a)] == second[str(a)] == []
    assert again.batches == []
