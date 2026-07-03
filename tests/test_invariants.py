"""The airtight contract: lossless / round-trip / bounds / determinism / no-crash.

Enforced three ways: hand-curated edge cases, the real standard library, and property-based fuzzing.
"""
import glob
import os

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from helpers import assert_airtight
from skim import skim_file

# ----------------------------------------------------------------- edge cases
EDGE = {
    "empty": "",
    "whitespace_only": "   \n\t\n  \n",
    "comments_only": "# a\n# b\n# c\n",
    "single_expr": "1 + 1\n",
    "no_trailing_newline": "x = 1",
    "crlf": "def f():\r\n    return 1\r\n",
    "unicode_ident": "def gru():\n    cafe = '☕'\n    return cafe\n",
    "emoji_string": "X = '\U0001f600\U0001f680'\n",
    "oneliner": "def f(): return 1\n",
    "decorated_oneliner": "@deco\ndef f(): return 1\n",
    "stacked_decorators": "@a\n@b(1)\n@c.d\ndef f():\n    return 1\n",
    "overload": ("from typing import overload\nclass C:\n"
                 "    @overload\n    def g(self, x: int) -> int: ...\n"
                 "    @overload\n    def g(self, x: str) -> str: ...\n"
                 "    def g(self, x): return x\n"),
    "async_fn": "async def h():\n    return await x()\n",
    "nested": "def outer():\n    def inner():\n        return 1\n    return inner\n",
    "conditional_def": ("import sys\nif sys.platform == 'win32':\n    def p(): return 1\n"
                        "else:\n    def p(): return 2\n"),
    "try_import": "try:\n    import ujson as j\nexcept ImportError:\n    import json as j\n",
    "class_pass": "class E(Exception):\n    pass\n",
    "class_docstring_only": 'class D:\n    """just a doc"""\n',
    "module_docstring": '"""line1\nline2\nline3"""\nx = 1\n',
    "multiline_sig": "def f(\n    a,\n    b,\n    c,\n):\n    return a\n",
    "syntax_error": "def f(:\n    not valid python here\n",
    "long_line": "x = " + "1+" * 4000 + "1\n",
    "many_tiny_fns": "".join(f"def f{i}(): return {i}\n" for i in range(500)),
    # exotic separators are CONTENT, not line endings: splitlines() would split these mid-line,
    # shifting every ast/tree-sitter line number below them (regression: split("\n") fix)
    "formfeed_in_string": "A = 'a\fb'\ndef f():\n    return A\n",
    "vtab_in_string": "B = 'a\vb'\ndef g():\n    return B\n",
    "unicode_linesep_in_string": "S = 'x\u2028y\u2029z'\ndef h():\n    return S\n",
    "nel_in_comment": "# note\x85tail\nC = 1\n",
}


@pytest.mark.parametrize("name", list(EDGE))
def test_edge_cases_airtight(name):
    assert_airtight(EDGE[name], ".py")


# ----------------------------------------------------------------- real corpus
def _stdlib_sample(n=60):
    libdir = os.path.dirname(os.__file__)
    files = [f for f in sorted(glob.glob(os.path.join(libdir, "*.py"))) if os.path.getsize(f) > 800]
    return files[:n]


@pytest.mark.parametrize("path", _stdlib_sample())
def test_stdlib_airtight(path):
    r = skim_file(path)
    lines = r._lines
    covered = set()
    for s, e in r.anchors.values():
        covered.update(range(s, e + 1))
    skel = set(r.skeleton.split("\n"))
    lost = [i for i, ln in enumerate(lines, 1) if ln.strip() and i not in covered and ln not in skel]
    assert lost == [], f"{path}: lost lines {lost[:10]}"
    assert all(r.expand(a) == "\n".join(lines[s - 1:e]) for a, (s, e) in r.anchors.items())


# ----------------------------------------------------------------- fuzzing
_SNIPPETS = [
    "import os",
    "from sys import argv",
    "X = 1",
    "Y = [1, 2, 3]",
    "# a standalone comment",
    "lam = lambda x: x + 1",
    "def f():\n    return 1",
    "def g(a, b=2):\n    '''doc'''\n    return a + b",
    "async def h():\n    await x()",
    "@deco\ndef d(): ...",
    "class C:\n    '''c'''\n    def m(self):\n        return self",
    "class E(Exception):\n    pass",
    "if True:\n    def cond():\n        return 1",
    "try:\n    import ujson\nexcept ImportError:\n    import json",
    "def multi(\n    a,\n    b,\n):\n    return a",
    "for _i in range(3):\n    pass",
    '"""module level string"""',
]


@st.composite
def _py_program(draw):
    n = draw(st.integers(min_value=1, max_value=8))
    return "\n\n".join(draw(st.sampled_from(_SNIPPETS)) for _ in range(n)) + "\n"


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(_py_program())
def test_fuzz_python_airtight(src):
    assert_airtight(src, ".py")


@settings(max_examples=200, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(st.text())
def test_fuzz_arbitrary_text_airtight(src):
    assert_airtight(src, ".txt")


# Targeted dedup fuzzing: random multi-line blocks, repeated -> exercises the path that lost data.
_LINE = st.text(alphabet="abcXYZ 0123_./:-", min_size=1, max_size=18).filter(lambda s: s.strip())


@st.composite
def _repeated_blocks(draw):
    block = "\n".join(draw(st.lists(_LINE, min_size=1, max_size=5)))
    reps = draw(st.integers(min_value=2, max_value=5))
    return "\n\n".join([block] * reps) + "\n"


@settings(max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow])
@given(_repeated_blocks())
def test_fuzz_dedup_airtight(src):
    assert_airtight(src, ".log")
