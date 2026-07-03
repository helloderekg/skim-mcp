"""Score the expand-loop from a real session log - the eval gate, mechanized.

For each question in QUESTIONS.md the answer lives inside a collapsed anchor (locked by
tests/test_eval_premise.py). This script derives the answer-key anchors from the fixtures
themselves (content search, so it survives skeleton changes), then reads skim_calls.jsonl
and reports, per session: did an expand of the right anchor (or a search that surfaced it)
happen for each question's file?

    uv run python eval/score_expand_loop.py [path/to/skim_calls.jsonl] [--session ID]

Protocol: mount skim, ask the QUESTIONS.md questions in a fresh session (no hints), then run this.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))
from skim import skim_file  # noqa: E402
from skim.logpath import default_log_path  # noqa: E402

_EVAL = os.path.dirname(os.path.abspath(__file__))

# question id -> (fixture file, distinctive answer marker). Markers must be BODY content that
# never appears in the skeleton (signatures like "def retry_policy" are IN the skeleton, so they
# match no anchor and the question could never score). Locked by tests/test_eval_premise.py.
KEY = {
    "Q1 gold discount":    ("widget.py", "0.18"),
    "Q2 token prefix":     ("widget.py", "sk_live_"),
    "Q3 retry wait":       ("widget.py", "backoff"),
    "Q4 free shipping":    ("widget.py", "weight_kg <= 5"),
    "Q5 status 418":       ("widget.py", "teapot"),
    "Q6 exit after retries": ("run.log", "exit code 70"),
    "Q7 unreachable host": ("run.log", "10.0.0.9:5432"),
}


def answer_anchors():
    """Derive, per question, the fixture's anchor ids whose expansion contains the marker."""
    out = {}
    for q, (fname, marker) in KEY.items():
        r = skim_file(os.path.join(_EVAL, fname))
        aids = [a for a in r.anchors if marker in r.expand(a)]
        out[q] = (fname, marker, set(aids))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("log", nargs="?", default=default_log_path())
    ap.add_argument("--session", default=None, help="score only this session id")
    args = ap.parse_args()
    if not os.path.isfile(args.log):
        print(f"no log at {args.log}")
        return

    key = answer_anchors()
    # session -> {basename -> set(expanded anchor ids)}, plus search counts
    expanded, searched, opened = {}, {}, {}
    handle_file = {}                                   # handle -> fixture basename
    for raw in open(args.log, encoding="utf-8", errors="replace"):
        try:
            e = json.loads(raw)
        except json.JSONDecodeError:
            continue
        sid = e.get("session", "unlabeled")
        if args.session and sid != args.session:
            continue
        call = e.get("call")
        if call == "skim_open" and "path" in e and "handle" in e:
            handle_file[e["handle"]] = os.path.basename(e["path"])
            opened.setdefault(sid, set()).add(os.path.basename(e["path"]))
        elif call == "skim_expand" and e.get("handle") in handle_file:
            f = handle_file[e["handle"]]
            expanded.setdefault(sid, {}).setdefault(f, set()).update(e.get("found", []))
        elif call == "skim_search" and e.get("handle") in handle_file:
            searched.setdefault(sid, {}).setdefault(handle_file[e["handle"]], 0)
            searched[sid][handle_file[e["handle"]]] += 1

    sessions = sorted(set(opened) | set(expanded))
    if not sessions:
        print("log has no skim_open events on the eval fixtures yet")
        return
    for sid in sessions:
        print(f"\nsession {sid}")
        right = total = 0
        for q, (fname, marker, aids) in key.items():
            if fname not in opened.get(sid, set()):
                continue                                # question's file never opened -> not attempted
            total += 1
            got = expanded.get(sid, {}).get(fname, set())
            hit = bool(got & aids)
            right += hit
            print(f"  {q:<24} {'EXPANDED right anchor' if hit else 'NO expand of ' + '/'.join(sorted(aids))}"
                  f"  (expanded: {sorted(got) or '-'})")
        if total:
            print(f"  expand-when-needed: {right}/{total} = {100 * right / total:.0f}%  "
                  f"(pass bar in QUESTIONS.md: >= 80%)")
        for f, n in searched.get(sid, {}).items():
            print(f"  searches on {f}: {n}")


if __name__ == "__main__":
    main()
