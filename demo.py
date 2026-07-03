"""Run the skim core on real files and print measured before/after token counts.

    python demo.py                       # demo on examples/sample.log
    python demo.py path/to/file.py ...   # skim any files
"""
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # skimmed files may hold non-ASCII
except Exception:
    pass

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from skim import skim_file, token_basis  # noqa: E402


def show(path: str) -> None:
    r = skim_file(path)
    rep = r.report()
    print("=" * 64)
    print(json.dumps(rep, indent=2))
    print(f"\n--- skeleton (first 40 lines of {os.path.basename(path)}) ---")
    print("\n".join(r.skeleton.splitlines()[:40]))
    if r.anchors:
        aid = list(r.anchors)[len(r.anchors) // 2]
        body = r.expand(aid)
        print(f'\n--- expand("{aid}") -> {len(body.splitlines())} exact lines (first 8) ---')
        print("\n".join(body.splitlines()[:8]))


if __name__ == "__main__":
    print("token basis:", token_basis())
    targets = sys.argv[1:] or [os.path.join("examples", "sample.log")]
    for t in targets:
        if os.path.exists(t):
            show(t)
        else:
            print(f"(skip, not found) {t}")
