"""Lock the eval premise: every eval answer is hidden from the skeleton, recoverable by expand.

eval/QUESTIONS.md claims each answer lives in a collapsed span - "a correct answer requires an
expand". If a skeletonizer or retention change ever surfaces one of these markers into the
skeleton, the eval stops measuring under-fetch and this test fails first.
"""
import os
import sys

from skim import skim_file

_EVAL = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "eval")
sys.path.insert(0, _EVAL)
from score_expand_loop import KEY  # noqa: E402  - lock the scorer's own marker table

# distinctive substrings only (short markers like "9" would false-positive on anchor ids)
MARKERS = {
    "widget.py": ["0.18", "sk_live_", "teapot", "backoff", "weight_kg <= 5"],
    "run.log": ["10.0.0.9:5432", "exit code 70"],
}


def _anchored_text(r):
    return "\n\n".join(r.expand(a) for a in r.anchors)


def test_eval_answers_hidden_but_recoverable():
    for fname, markers in MARKERS.items():
        r = skim_file(os.path.join(_EVAL, fname))
        hidden = _anchored_text(r)
        for m in markers:
            assert m not in r.skeleton, f"{fname}: answer marker {m!r} leaked into the skeleton"
            assert m in hidden, f"{fname}: answer marker {m!r} not recoverable via any anchor"


def test_scorer_markers_resolve_to_anchors_and_stay_hidden():
    # The regression this locks: a KEY marker that names a SIGNATURE ("def retry_policy") is
    # visible in the skeleton and inside no anchor, so the scorer could never credit an expand.
    for q, (fname, marker) in KEY.items():
        r = skim_file(os.path.join(_EVAL, fname))
        aids = [a for a in r.anchors if marker in r.expand(a)]
        assert aids, f"{q}: marker {marker!r} matches no anchor - unscoreable question"
        assert marker not in r.skeleton, f"{q}: marker {marker!r} leaked into the skeleton"


def test_run_log_dedups_retry_blocks():
    r = skim_file(os.path.join(_EVAL, "run.log"))
    assert "identical to" in r.skeleton     # the repeated retry blocks collapse to pointers
