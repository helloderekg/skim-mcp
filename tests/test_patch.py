"""skim_patch: drift-refused, newline-preserving, span-exact writes with a fresh handle."""
import os
import sys
import tempfile

from skim.server import skim_expand, skim_open, skim_patch, skim_run, skim_search

SRC = (
    "def alpha():\n"
    "    return 1\n"
    "\n"
    "def beta():\n"
    "    return 2\n"
)


def _write(text: str, suffix: str = ".py") -> str:
    fd, p = tempfile.mkstemp(suffix=suffix)
    os.close(fd)
    with open(p, "w", encoding="utf-8", newline="") as f:   # newline="": bytes land exactly as given
        f.write(text)
    return p


def _read_bytes(p: str) -> bytes:
    with open(p, "rb") as f:
        return f.read()


def _anchor_containing(handle: str, marker: str) -> str:
    hits = skim_search(handle, marker)["hits"]
    aids = [h["anchor"] for h in hits if h["anchor"].startswith("a")]
    assert aids, f"no anchor covers {marker!r}"
    return aids[0]


def test_patch_anchor_roundtrip():
    p = _write(SRC)
    try:
        opened = skim_open(p)
        aid = _anchor_containing(opened["handle"], "return 1")
        res = skim_patch(opened["handle"], aid, "    return 42")
        assert res["ok"] and res["verified"]
        assert res["new_handle"] != opened["handle"]
        assert _read_bytes(p).decode("utf-8") == SRC.replace("    return 1", "    return 42")
    finally:
        os.unlink(p)


def test_patch_line_range():
    p = _write(SRC)
    try:
        opened = skim_open(p)
        res = skim_patch(opened["handle"], "L4-5", "def beta():\n    x = 2\n    return x")
        assert res["ok"]
        want = "def alpha():\n    return 1\n\ndef beta():\n    x = 2\n    return x\n"
        assert _read_bytes(p).decode("utf-8") == want
    finally:
        os.unlink(p)


def test_patch_refuses_on_drift():
    p = _write(SRC)
    try:
        opened = skim_open(p)
        with open(p, "a", encoding="utf-8", newline="") as f:
            f.write("# drifted\n")
        res = skim_patch(opened["handle"], "L1-1", "def alpha_renamed():")
        assert "changed on disk" in res["error"]
        assert "# drifted" in _read_bytes(p).decode("utf-8")   # file untouched by the refused patch
    finally:
        os.unlink(p)


def test_patch_unknown_handle_and_anchor():
    assert "unknown handle" in skim_patch("nope:00000000", "a1", "x")["error"]
    p = _write(SRC)
    try:
        opened = skim_open(p)
        assert "unknown anchor" in skim_patch(opened["handle"], "a999", "x")["error"]
        assert "out of bounds" in skim_patch(opened["handle"], "L90-99", "x")["error"]
    finally:
        os.unlink(p)


def test_patch_refuses_run_handles():
    res = skim_run(f'"{sys.executable}" -c "print(123)"')
    assert res["exit_code"] == 0
    out = skim_patch(res["handle"], "L1-1", "x")
    assert "does not reference a file" in out["error"]


def test_patch_preserves_crlf():
    p = _write("a = 1\r\nb = 2\r\nc = 3\r\n")
    try:
        opened = skim_open(p)
        res = skim_patch(opened["handle"], "L2-2", "b = 99")
        assert res["ok"] and res["newline_style"] == "crlf"
        assert _read_bytes(p) == b"a = 1\r\nb = 99\r\nc = 3\r\n"
    finally:
        os.unlink(p)


def test_patch_no_trailing_newline_kept():
    p = _write("a = 1\nb = 2")            # no trailing newline
    try:
        opened = skim_open(p)
        res = skim_patch(opened["handle"], "L1-1", "a = 7")
        assert res["ok"]
        assert _read_bytes(p) == b"a = 7\nb = 2"
    finally:
        os.unlink(p)


def test_patch_disabled_env(monkeypatch):
    monkeypatch.setenv("SKIM_PATCH_DISABLED", "1")
    p = _write(SRC)
    try:
        opened = skim_open(p)
        assert "disabled" in skim_patch(opened["handle"], "L1-1", "x")["error"]
    finally:
        os.unlink(p)


def test_old_handle_still_reads_its_snapshot():
    p = _write(SRC)
    try:
        opened = skim_open(p)
        aid = _anchor_containing(opened["handle"], "return 1")
        before = skim_expand(opened["handle"], [aid])["spans"][aid]
        res = skim_patch(opened["handle"], aid, "    return 42")
        assert res["ok"]
        after_old = skim_expand(opened["handle"], [aid])["spans"][aid]
        assert after_old == before                     # snapshot semantics, never silent drift
        whole = f"L1-{len(SRC.split(chr(10)))}"
        assert "42" in skim_expand(res["new_handle"], [whole])["spans"][whole]
    finally:
        os.unlink(p)
