"""Honest net-savings report from real skim usage.

Reads skim_calls.jsonl (written by the MCP server on every call) and computes, per file you
skim-opened: what reading it in full would have cost vs. what skim actually cost you
(skeleton + every expand + every search). If you expand everything, net savings shrink toward
zero -- that's the truth, and this report shows it.

    uv run python skim_report.py [path/to/skim_calls.jsonl]
"""
import collections
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from skim.logpath import default_log_path  # noqa: E402


def main():
    log = sys.argv[1] if len(sys.argv) > 1 else default_log_path()
    if not os.path.exists(log):
        print(f"No log at {log}. Mount skim, use it on real files, then run this.")
        return

    H = collections.defaultdict(lambda: {
        "path": "?", "full": 0, "skel": 0, "exp": 0, "srch": 0,
        "opens": 0, "expands": 0, "searches": 0,
    })
    for raw in open(log, encoding="utf-8", errors="replace"):
        raw = raw.strip()
        if not raw:
            continue
        try:
            e = json.loads(raw)
        except json.JSONDecodeError:
            continue
        h = e.get("handle")
        if not h:
            continue
        r = H[h]
        call = e.get("call")
        if call == "skim_open" and "full_tokens" in e:
            r["path"] = e.get("path", "?")
            r["full"] = e["full_tokens"]
            r["skel"] = e.get("result_tokens", e["skeleton_tokens"])   # true delivered payload
            r["opens"] += 1
        elif call == "skim_expand":
            r["exp"] += e.get("result_tokens", e.get("expand_tokens", 0))
            r["expands"] += 1
        elif call == "skim_search":
            r["srch"] += e.get("result_tokens", e.get("search_tokens", 0))
            r["searches"] += 1

    rows = [r for r in H.values() if r["full"] > 0]
    if not rows:
        print("Log has no skim_open events with token counts yet.")
        return

    print(f"{'file':<26}{'full read':>10}{'skim cost':>10}{'net saved':>10}{'saved%':>8}   o/e/s")
    print("-" * 78)
    tb = tc = 0
    for r in sorted(rows, key=lambda x: x["full"] - (x["skel"] + x["exp"] + x["srch"]), reverse=True):
        cost = r["skel"] + r["exp"] + r["srch"]
        net = r["full"] - cost
        tb += r["full"]
        tc += cost
        name = os.path.basename(r["path"])[:25]
        print(f"{name:<26}{r['full']:>10}{cost:>10}{net:>10}{100 * net / r['full']:>7.1f}%"
              f"   {r['opens']}/{r['expands']}/{r['searches']}")
    print("-" * 78)
    print(f"{'SESSION TOTAL':<26}{tb:>10}{tc:>10}{tb - tc:>10}{100 * (tb - tc) / tb:>7.1f}%")
    print(f"\nNet: skim cost {tc:,} tokens vs {tb:,} to read those files in full "
          f"-> {tb - tc:,} saved ({100 * (tb - tc) / tb:.1f}%).")
    print("baseline = full_tokens of files you skim-opened; skim cost = skeleton + expands + searches.")
    print("o/e/s = opens / expands / searches. (token counts via tiktoken, a proxy for Claude's.)")


if __name__ == "__main__":
    main()
