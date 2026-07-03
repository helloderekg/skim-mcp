"""Live token-meter accounting + web handler (never crash; correct net savings)."""
import json
import os
import tempfile

from skim.meter import compute, snapshot_text


def _log(events) -> str:
    fd, p = tempfile.mkstemp(suffix=".jsonl")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e) + "\n")
    return p


def test_missing_log_is_clean():
    d = compute(os.path.join(tempfile.gettempdir(), "nope_skim_meter.jsonl"))
    assert d["log_exists"] is False
    assert d["tokens_in"] == 0 and d["tokens_out"] == 0 and d["saved_pct"] == 0.0
    assert "no log yet" in snapshot_text(d)


def test_savings_math_across_tools():
    p = _log([
        {"call": "skim_open", "path": "/x/big.py", "full_tokens": 10000, "result_tokens": 2000},
        {"call": "skim_expand", "handle": "big.py:1", "result_tokens": 500},
        {"call": "skim_search", "handle": "big.py:1", "result_tokens": 100},
        {"call": "skim_run", "command": "pytest", "full_tokens": 4000, "result_tokens": 600},
        {"call": "skim_repo", "root": "/x/src", "full_tokens": 8000, "result_tokens": 1500},
    ])
    try:
        d = compute(p)
        # in = 10000 + 4000 + 8000 (open/run/repo baselines); expand/search add NO baseline
        assert d["tokens_in"] == 22000
        # out = every result_tokens delivered
        assert d["tokens_out"] == 2000 + 500 + 100 + 600 + 1500
        assert d["saved"] == 22000 - 4700
        assert d["saved_pct"] == round(100 * (22000 - 4700) / 22000, 1)
        assert d["calls"] == 5
        assert d["by_tool"]["skim_open"] == 1
        assert d["recent"][0]["call"] == "skim_repo"        # newest first
    finally:
        os.unlink(p)


def test_error_events_and_garbage_ignored():
    p = _log([
        {"call": "skim_open", "path": "p", "error": "not_a_file"},   # errors don't count
        {"call": "skim_open", "path": "/a.py", "full_tokens": 100, "result_tokens": 40},
    ])
    # append a non-JSON line
    with open(p, "a", encoding="utf-8") as f:
        f.write("not json at all\n")
    try:
        d = compute(p)
        assert d["calls"] == 1 and d["tokens_in"] == 100 and d["tokens_out"] == 40
    finally:
        os.unlink(p)


def test_expand_only_can_net_negative():
    # tiny output where the skim wrapper costs more than the baseline -> honest negative
    p = _log([{"call": "skim_run", "command": "echo hi", "full_tokens": 5, "result_tokens": 120}])
    try:
        d = compute(p)
        assert d["saved"] == 5 - 120
        assert d["saved_pct"] < 0
    finally:
        os.unlink(p)


def test_web_data_endpoint_serves_json():
    from http.server import HTTPServer
    import threading
    import urllib.request
    from skim.meter import _make_handler

    p = _log([{"call": "skim_open", "path": "/a.py", "full_tokens": 1000, "result_tokens": 200}])
    srv = HTTPServer(("127.0.0.1", 0), _make_handler(p))
    threading.Thread(target=srv.handle_request, daemon=True).start()
    try:
        port = srv.server_address[1]
        body = urllib.request.urlopen(f"http://127.0.0.1:{port}/data", timeout=5).read()
        d = json.loads(body)
        assert d["tokens_in"] == 1000 and d["tokens_out"] == 200 and d["saved_pct"] == 80.0
    finally:
        srv.server_close()
        os.unlink(p)


def test_web_rejects_foreign_host_header():
    # DNS-rebinding guard: when bound to loopback, a request whose Host is a foreign domain
    # must get 403 (a hostile page rebinding its DNS to 127.0.0.1 sends its own hostname).
    import http.client
    import threading
    from http.server import HTTPServer
    from skim.meter import _make_handler

    p = _log([{"call": "skim_open", "path": "/a.py", "full_tokens": 100, "result_tokens": 10}])
    srv = HTTPServer(("127.0.0.1", 0), _make_handler(p))
    try:
        port = srv.server_address[1]
        threading.Thread(target=srv.handle_request, daemon=True).start()
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/data", headers={"Host": "evil.example"})
        assert conn.getresponse().status == 403
        conn.close()
        threading.Thread(target=srv.handle_request, daemon=True).start()
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request("GET", "/data", headers={"Host": f"localhost:{port}"})
        assert conn.getresponse().status == 200          # loopback Hosts still fine
        conn.close()
    finally:
        srv.server_close()
        os.unlink(p)


def test_price_is_opt_in():
    from skim.meter import _with_price
    d = {"saved": 2_000_000}
    assert "saved_usd" not in _with_price(dict(d), 0)               # no default price, ever
    priced = _with_price(dict(d), 3.0)
    assert priced["saved_usd"] == 6.0 and priced["price_per_mtok"] == 3.0


def test_dashboard_page_escapes_data_interpolations():
    # tripwire: every data-derived value interpolated into innerHTML goes through esc()
    # (targets are file paths / shell commands / session labels - hostile strings must render as text)
    from skim.meter import _PAGE
    assert "const esc" in _PAGE
    for needle in ("esc(r.call)", "esc(r.target||'')", "esc(nm)", "esc(s.id)", "esc(ttl)"):
        assert needle in _PAGE


def test_per_session_breakdown():
    p = _log([
        {"call": "_session_start", "session": "aaa", "id": "aaa", "cwd": "/proj/one", "started": 100},
        {"call": "skim_open", "session": "aaa", "path": "/x.py", "full_tokens": 1000, "result_tokens": 200},
        {"call": "_session_start", "session": "bbb", "id": "bbb", "named": True, "cwd": "/proj/two", "started": 200},
        {"call": "skim_open", "session": "bbb", "path": "/y.py", "full_tokens": 500, "result_tokens": 100},
        {"call": "skim_expand", "session": "bbb", "handle": "y.py:1", "result_tokens": 50},
    ])
    try:
        d = compute(p)
        assert d["tokens_in"] == 1500 and d["tokens_out"] == 350       # overall = sum of both sessions
        assert len(d["sessions"]) == 2
        assert d["sessions"][0]["id"] == "bbb"                          # newest (started 200) first
        by = {s["id"]: s for s in d["sessions"]}
        assert by["aaa"]["tokens_in"] == 1000 and by["aaa"]["saved_pct"] == 80.0
        assert by["bbb"]["calls"] == 2 and by["bbb"]["label"] == "bbb"  # named -> label is the name
        assert by["aaa"]["label"] == "x.py"                            # unnamed -> first file touched
    finally:
        os.unlink(p)


def test_clear_archives_ghost_and_resets_view():
    from skim.meter import clear_log
    p = _log([{"call": "skim_open", "path": "/a.py", "full_tokens": 100, "result_tokens": 20, "t": 1000}])
    ghost, wm = None, p + ".cleared"
    try:
        assert compute(p)["calls"] == 1                 # visible before clear
        ghost = clear_log(p)
        assert ghost and os.path.isfile(ghost)          # ghost keeps history (a copy, not a rename)
        assert "skim_open" in open(ghost, encoding="utf-8").read()
        assert os.path.isfile(p)                        # live log NEVER renamed/truncated -> can't lock
        assert os.path.isfile(wm)                       # watermark recorded
        assert compute(p)["calls"] == 0                 # view reset: pre-clear events hidden
        assert clear_log(os.path.join(tempfile.gettempdir(), "nope_x_skim.jsonl")) is None
    finally:
        for f in (p, ghost, wm):
            if f and os.path.exists(f):
                os.unlink(f)


def test_started_session_with_no_calls_is_listed():
    p = _log([
        {"call": "_session_start", "session": "old", "id": "old", "started": 100, "t": 100},
        {"call": "skim_open", "session": "old", "path": "/a.py", "full_tokens": 100, "result_tokens": 20, "t": 110},
        {"call": "_session_start", "session": "fresh", "id": "fresh", "started": 200, "t": 200},
    ])
    try:
        d = compute(p)
        assert [s["id"] for s in d["sessions"]] == ["fresh", "old"]   # by last_active desc
        fresh = next(s for s in d["sessions"] if s["id"] == "fresh")
        assert fresh["calls"] == 0 and fresh["last_active"] == 200    # listed despite zero skim calls
        old = next(s for s in d["sessions"] if s["id"] == "old")
        assert old["last_active"] == 110                              # last skim call, not the start
        assert d["session_count"] == 2
    finally:
        os.unlink(p)


def test_legacy_lines_bucket_unlabeled():
    p = _log([{"call": "skim_open", "path": "/z.py", "full_tokens": 100, "result_tokens": 30}])
    try:
        d = compute(p)
        assert len(d["sessions"]) == 1 and d["sessions"][0]["id"] == "unlabeled"
        assert d["tokens_in"] == 100 and d["tokens_out"] == 30
    finally:
        os.unlink(p)
