"""MCP server tools: shapes, round-trip, and error handling (never crash)."""
import os
import sys
import tempfile

from skim.server import skim_expand, skim_open, skim_repo, skim_run, skim_search

_SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")

PY = sys.executable


def _cmd(code: str) -> str:
    return f'"{PY}" -c "{code}"'


def _write(src: str) -> str:
    fd, p = tempfile.mkstemp(suffix=".py")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(src)
    return p


def test_open_missing_path():
    r = skim_open(os.path.join(tempfile.gettempdir(), "definitely_not_here_skim.py"))
    assert "error" in r


def test_open_returns_clean_shape():
    p = _write("def f():\n    return 42\n\ndef g():\n    return 7\n")
    try:
        r = skim_open(p)
        assert "handle" in r and "skeleton" in r and r["anchor_count"] >= 1
        assert "anchors" not in r            # redundant id array removed
        assert "guidance" not in r           # duplicate steering field removed
        assert r["report"]["full_tokens"] >= 1
    finally:
        os.unlink(p)


def test_expand_roundtrip():
    p = _write("def f():\n    return 42\n")
    try:
        r = skim_open(p)
        e = skim_expand(r["handle"], ["a1"])
        assert "42" in e["spans"]["a1"]
    finally:
        os.unlink(p)


def test_expand_unknown_handle():
    assert "error" in skim_expand("nope:123", ["a1"])


def test_expand_unknown_anchor():
    p = _write("def f():\n    return 1\n")
    try:
        r = skim_open(p)
        e = skim_expand(r["handle"], ["zzz"])
        assert "ERROR" in e["spans"]["zzz"]
    finally:
        os.unlink(p)


def test_search_finds_and_bounds():
    p = _write("def alpha():\n    return 1\n\ndef beta():\n    return 2\n")
    try:
        r = skim_open(p)
        assert skim_search(r["handle"], "beta")["count"] >= 1
        assert skim_search(r["handle"], "zzz_absent")["count"] == 0
    finally:
        os.unlink(p)


def test_search_unknown_handle():
    assert "error" in skim_search("nope:123", "x")


def test_skim_run_captures_output_and_exit():
    r = skim_run(_cmd("print('hello world')"))
    assert r["exit_code"] == 0
    assert "report" in r and "skeleton" in r
    assert "hello world" in r["skeleton"]


def test_skim_run_compresses_and_expands():
    r = skim_run(_cmd("print(chr(10).join('row %d ERROR code 500' % i for i in range(80)))"))
    assert r["exit_code"] == 0
    assert r["anchor_count"] >= 1                      # 80 lines -> compressed
    # full output is recoverable via expand
    body = "".join(skim_expand(r["handle"], [f"a{i}"]).get("spans", {}).get(f"a{i}", "")
                   for i in range(1, r["anchor_count"] + 1))
    assert "row 79 ERROR code 500" in (r["skeleton"] + body)


def test_skim_run_disabled_via_env(monkeypatch):
    monkeypatch.setenv("SKIM_RUN_DISABLED", "1")
    r = skim_run(_cmd("print('should not run')"))
    assert "error" in r and "disabled" in r["error"]
    assert "skeleton" not in r


def test_skim_run_nonzero_exit():
    r = skim_run(_cmd("import sys; sys.exit(3)"))
    assert r["exit_code"] == 3


def test_skim_run_timeout():
    r = skim_run(_cmd("import time; time.sleep(5)"), timeout=1)
    assert "error" in r and "tim" in r["error"].lower()


def test_skim_repo_maps_directory():
    r = skim_repo(_SRC, budget_tokens=4000)
    assert r["files_included"] >= 1
    f0 = r["files"][0]
    assert f0["handle"] and isinstance(f0["skeleton"], str)
    if f0["anchors"]:
        e = skim_expand(f0["handle"], ["a1"])   # exact code recoverable across files
        assert "a1" in e["spans"]


def test_skim_repo_query_ranks_and_budgets():
    r = skim_repo(_SRC, query="skim_expand", budget_tokens=3000)
    assert r["query"] == "skim_expand"
    assert r["files_included"] >= 1
    assert r["used_tokens"] <= 3000 + 6000   # budget respected (allow one over-budget file)


def test_skim_repo_not_a_directory():
    assert "error" in skim_repo(os.path.abspath(__file__))


def test_open_directory_clean_error():
    r = skim_open(os.path.dirname(os.path.abspath(__file__)))   # a directory, not a file
    assert "error" in r                                         # clean error, never a crash


def test_reopen_changed_file_new_handle_old_snapshot_intact():
    # regression: handles hash CONTENT, so a re-open of a changed file can never let old anchor
    # ids silently resolve against new lines - each snapshot keeps its own consistent handle
    p = _write("def f():\n    a = 1\n    b = 2\n    return a + b\n")
    try:
        r1 = skim_open(p)
        with open(p, "w", encoding="utf-8") as f:
            f.write("def f():\n    x = 9\n    y = 8\n    return x * y\n")
        r2 = skim_open(p)
        assert r1["handle"] != r2["handle"]
        assert "a + b" in skim_expand(r1["handle"], ["a1"])["spans"]["a1"]
        assert "x * y" in skim_expand(r2["handle"], ["a1"])["spans"]["a1"]
    finally:
        os.unlink(p)


def test_skim_run_rerun_with_new_output_gets_new_handle():
    # regression: the same command run twice with different output must not share a handle
    fd, data = tempfile.mkstemp(suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("FIRST RUN MARKER\n" * 3)
    cmd = _cmd(f"print(open(r'{data}').read())")
    try:
        r1 = skim_run(cmd)
        with open(data, "w", encoding="utf-8") as f:
            f.write("SECOND RUN MARKER\n" * 3)
        r2 = skim_run(cmd)
        assert r1["handle"] != r2["handle"]
        assert skim_search(r1["handle"], "FIRST RUN MARKER")["count"] >= 1    # old snapshot intact
        assert skim_search(r2["handle"], "SECOND RUN MARKER")["count"] >= 1
    finally:
        os.unlink(data)


def test_skim_run_decodes_utf8_output():
    # regression: output is decoded as UTF-8 on every platform (locale cp1252 would mojibake this)
    r = skim_run(_cmd("import sys; sys.stdout.reconfigure(encoding='utf-8'); "
                      "print('utf8marker ' + chr(233) + chr(10004))"))
    assert r["exit_code"] == 0
    assert "utf8marker é✔" in r["skeleton"]


def test_search_zero_and_negative_bound():
    p = _write("def aaa():\n    return 1\n\ndef aab():\n    return 2\n")
    try:
        r = skim_open(p)
        assert skim_search(r["handle"], "a", max_results=0)["count"] == 0
        assert skim_search(r["handle"], "a", max_results=-5)["count"] == 0
    finally:
        os.unlink(p)


def test_open_with_query_returns_matches():
    p = _write("def alpha():\n    magic_needle = 42\n    return magic_needle\n")
    try:
        r = skim_open(p, query="magic_needle")
        assert r["matches"] and r["matches"][0]["anchor"] == "a1"   # points into the folded body
        assert "matches" not in skim_open(p)                        # absent without a query
    finally:
        os.unlink(p)


def test_expand_literal_line_ranges():
    p = _write("L1 = 1\nL2 = 2\nL3 = 3\nL4 = 4\n")
    try:
        r = skim_open(p)
        e = skim_expand(r["handle"], ["L2-3"])
        assert e["spans"]["L2-3"] == "L2 = 2\nL3 = 3"               # byte-exact, 1-based inclusive
        bad = skim_expand(r["handle"], ["L9-99"])
        assert "ERROR" in bad["spans"]["L9-99"]
    finally:
        os.unlink(p)


def test_repo_scan_not_truncated_normally():
    r = skim_repo(_SRC, budget_tokens=2000)
    assert r["scan_truncated"] is False


def test_lru_evicts_oldest_handle(monkeypatch):
    import skim.server as srv
    monkeypatch.setattr(srv, "_SESSIONS_MAX", 2)
    paths = [_write(f"def f{i}():\n    return {i}\n") for i in range(3)]
    try:
        handles = [skim_open(p)["handle"] for p in paths]
        assert "error" in skim_expand(handles[0], ["a1"])           # oldest evicted, clean error
        assert "a1" in skim_expand(handles[2], ["a1"])["spans"]     # newest still alive
    finally:
        for p in paths:
            os.unlink(p)


def test_repo_ranks_by_import_graph_without_query():
    d = tempfile.mkdtemp()
    try:
        with open(os.path.join(d, "util.py"), "w", encoding="utf-8") as f:
            f.write("def helper():\n    return 1\n")
        for name in ("a.py", "b.py", "c.py"):
            with open(os.path.join(d, name), "w", encoding="utf-8") as f:
                f.write("import util\n\ndef use():\n    return util.helper()\n" + "# pad\n" * 30)
        r = skim_repo(d, budget_tokens=4000)
        assert r["ranking"] == "imports"
        assert r["files"][0]["path"] == "util.py"   # most-imported first, despite being smallest
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def test_span_resource_matches_expand():
    from skim.server import skim_span
    p = _write("def f():\n    a = 1\n    b = 2\n    return a + b\n")
    try:
        r = skim_open(p)
        assert skim_span(r["handle"], "a1") == skim_expand(r["handle"], ["a1"])["spans"]["a1"]
        assert skim_span(r["handle"], "L1-2") == "def f():\n    a = 1"
        assert "ERROR" in skim_span(r["handle"], "zzz")
        assert "unknown handle" in skim_span("nope:123", "a1")
    finally:
        os.unlink(p)


def test_binary_file_gets_note_and_stays_recoverable():
    fd, p = tempfile.mkstemp(suffix=".bin")
    with os.fdopen(fd, "wb") as f:
        f.write(b"HDR\x00\x01\x02data\nline two with text\nmore\x00bytes\n")
    try:
        r = skim_open(p)
        assert "NUL bytes detected" in r["skeleton"]
        assert skim_search(r["handle"], "line two")["count"] == 1   # decoded text fully searchable
    finally:
        os.unlink(p)
