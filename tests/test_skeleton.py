"""Code-path behavior: what the skeleton shows vs collapses."""
import os
import tempfile

from skim import skim_file


def _skim(src: str):
    fd, p = tempfile.mkstemp(suffix=".py")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(src)
        return skim_file(p)
    finally:
        os.unlink(p)


def test_signature_shown_body_collapsed():
    r = _skim("def add(a, b):\n    x = a + b\n    return x\n")
    assert "def add(a, b):" in r.skeleton
    assert "x = a + b" not in r.skeleton                       # body collapsed out of the view
    assert any("x = a + b" in r.expand(a) for a in r.anchors)  # but recoverable


def test_overload_signatures_shown():
    src = ("from typing import overload\nclass C:\n"
           "    @overload\n    def g(self, x: int) -> int: ...\n"
           "    @overload\n    def g(self, x: str) -> str: ...\n"
           "    def g(self, x):\n        return x\n")
    r = _skim(src)
    assert "def g(self, x: int) -> int:" in r.skeleton
    assert "def g(self, x: str) -> str:" in r.skeleton


def test_class_and_methods_shown():
    r = _skim("class Foo:\n    def a(self):\n        return 1\n    def b(self):\n        return 2\n")
    assert "class Foo:" in r.skeleton
    assert "def a(self):" in r.skeleton
    assert "def b(self):" in r.skeleton


def test_imports_kept_verbatim():
    r = _skim("import os\nfrom sys import argv\n\ndef f():\n    return 1\n")
    assert "import os" in r.skeleton
    assert "from sys import argv" in r.skeleton


def test_multiline_signature_kept():
    r = _skim("def f(\n    a,\n    b,\n):\n    return a\n")
    assert "def f(" in r.skeleton and "a," in r.skeleton and "b," in r.skeleton


def test_report_fields():
    r = _skim("def f():\n    return 1\n")
    rep = r.report()
    assert rep["full_tokens"] >= 1 and rep["skeleton_tokens"] >= 1
    assert rep["ratio"] >= 0


def test_syntax_error_no_crash():
    r = _skim("def f(:\n    not valid python\n")
    assert isinstance(r.skeleton, str)   # fell back to generic, did not raise
