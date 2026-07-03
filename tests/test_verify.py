"""skim-verify: the user-facing falsification command (verdicts, exit codes, JSON mode)."""
import json
import os
import tempfile

from skim.verify import check_file, check_source, main


def _write(src: str, suffix: str = ".py") -> str:
    fd, p = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(src)
    return p


def test_pass_on_real_file(capsys):
    p = _write("def f():\n    return 1\n")
    try:
        assert main([p]) == 0
        out = capsys.readouterr().out
        assert out.startswith("PASS") and "reconstruction exact" in out
    finally:
        os.unlink(p)


def test_json_mode(capsys):
    p = _write("x = 1\n")
    try:
        assert main([p, "--json"]) == 0
        v = json.loads(capsys.readouterr().out.strip())
        assert v["ok"] is True and v["reconstruction_exact"] is True and v["deterministic"] is True
    finally:
        os.unlink(p)


def test_missing_file_is_crash_exit(capsys):
    assert main(["definitely_missing_9a8b7c.py"]) == 2
    assert "CRASH" in capsys.readouterr().out


def test_directory_rejected(tmp_path, capsys):
    assert main([str(tmp_path)]) == 2
    assert "directory" in capsys.readouterr().out


def test_multi_file_summary(capsys):
    p1, p2 = _write("a = 1\n"), _write("b = 2\n")
    try:
        assert main([p1, p2]) == 0
        assert "2/2 files pass" in capsys.readouterr().out
    finally:
        os.unlink(p1)
        os.unlink(p2)


def test_check_source_and_file_agree():
    v = check_source("def g():\n    return 2\n")
    assert v["ok"] and v["anchors"] >= 1
    p = _write("def g():\n    return 2\n")
    try:
        assert check_file(p)["ok"]
    finally:
        os.unlink(p)
