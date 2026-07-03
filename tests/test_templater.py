"""Drain-style templating: deterministic clustering + skeleton integration on dense blocks."""
import os
import tempfile

from helpers import assert_airtight
from skim import skim_file
from skim.templater import log_templates


def test_clusters_and_wildcards():
    # wildcarding is TOKEN-level (Drain semantics): whole whitespace tokens that vary become <*>
    lines = [f"GET /api/item id {i} took {i * 3} ms" for i in range(50)]
    shown, total = log_templates(lines)
    assert total == 1
    count, tpl, first = shown[0]
    assert count == 50 and first == 0
    assert tpl == "GET /api/item id <*> took <*> ms"


def test_min_count_filters_singletons():
    lines = ["one off line alpha", "another unique beta", "third unique gamma"]
    shown, total = log_templates(lines)
    assert shown == [] and total == 0               # nothing repeats -> no template noise


def test_deterministic():
    lines = [f"worker {i % 4} processed job {i}" for i in range(200)]
    assert log_templates(lines) == log_templates(lines)


def test_dense_block_shows_templates_in_skeleton():
    body = "\n".join(f"2026-07-02T10:00:{i % 60:02d} GET /api/u/{i} -> 200 in {i}ms" for i in range(80))
    src = "request log follows\n" + body + "\n"
    fd, p = tempfile.mkstemp(suffix=".log")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(src)
    try:
        r = skim_file(p)
        assert "~" in r.skeleton and "<*>" in r.skeleton    # the repeating shape is visible
    finally:
        os.unlink(p)
    assert_airtight(src, ".log")                    # templates are a view; contract unchanged
