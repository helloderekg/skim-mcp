"""skim invariant checker — thin wrapper kept for compatibility; the real one ships in the package.

    uv run python check_invariant.py <file>    # prints JSON; exit 0 ok / 1 violation / 2 crash
    skim-verify <file> [...]                   # the installed, multi-file form of the same checker
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from skim.verify import check_file, check_source  # noqa: E402,F401  (check_source re-exported)

if __name__ == "__main__":
    target = sys.argv[1]
    try:
        verdict = check_file(target)
    except Exception as ex:  # NO-CRASH violation
        print(json.dumps({"path": target, "crash": repr(ex), "ok": False}))
        sys.exit(2)
    print(json.dumps(verdict))
    sys.exit(0 if verdict["ok"] else 1)
