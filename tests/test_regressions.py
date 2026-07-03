"""Regression tests: inputs that once broke an invariant, now locked airtight.

Each case is (source, suffix). New findings from fuzzing / real use get appended here.
"""
from helpers import assert_airtight

CASES = [
    ("x = " + "1+" * 4000 + "1\n", ".py"),    # deep nesting -> ast RecursionError -> generic fallback, no crash
    ("count 20, total 10342.\n", ".log"),     # number followed by a period must still be retained
    ("def f(:\n    not valid\n", ".py"),       # syntax error -> generic fallback, no crash
    ("", ".py"),                               # empty file
    # --- dedup losslessness (adversarial campaign 2026-06-28) ---
    ("A\nB\n\nA\nB\n", ".log"),                # dedup must not drop the duplicate block's tail
    ("X\nY\n\nX\nY\n\nX\nY\n", ".txt"),        # triple-repeated block, each dup recoverable
    ('{\n  "k": 1\n}\n\n{\n  "k": 1\n}\n', ".json"),   # duplicate pretty-printed JSON objects
    ("x,y\n1,2\n\nx,y\n1,2\n", ".csv"),        # duplicate CSV rows
    ("@@@ A\n@@@ B\n\n@@@ A\n@@@ B\n", ".py"),  # dedup loss via python -> generic fallback
    ("def f(): x = (\n    1 +\n    2)\n", ".py"),  # multi-line one-liner body continuation
    ("﻿import os\n", ".py"),              # leading BOM
]


def test_known_regressions():
    for src, suffix in CASES:
        assert_airtight(src, suffix)
