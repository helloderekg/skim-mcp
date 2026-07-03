"""skim-verify - try to falsify skim's lossless contract on your own files.

Competing context tools claim reduction percentages; skim ships the checker that would expose it
if the guarantee were false. For ANY readable file, five invariants must hold:

  LOSSLESS        every non-blank original line is verbatim in the skeleton OR inside an anchor range
  ROUND-TRIP      expand(aid) returns exactly the original lines for that anchor's range
  BOUNDS          every anchor range is in-bounds (1 <= start <= end <= n_lines)
  RECONSTRUCTION  "\\n".join(lines) equals the decoded file exactly
  DETERMINISM     skimming twice yields a byte-identical skeleton

    skim-verify <file> [<file> ...]        # PASS/FAIL per file; exit 0 ok / 1 violation / 2 crash
    skim-verify --json <file>              # machine-readable verdicts

Run it against the gnarliest files you have. A reproducible FAIL is a bug - please report it.
"""
from __future__ import annotations
import argparse
import json
import os
import sys

from .skeleton import skim_file


def check_file(path: str) -> dict:
    """Check every invariant against one file on disk. Raises only on a NO-CRASH violation."""
    r1 = skim_file(path)
    r2 = skim_file(path)
    with open(path, encoding="utf-8", errors="replace") as f:
        disk = f.read()
    lines = r1._lines
    covered: set[int] = set()
    for s, e in r1.anchors.values():
        covered.update(range(s, e + 1))
    skel = set(r1.skeleton.split("\n"))
    lost = [i for i, ln in enumerate(lines, 1) if ln.strip() and i not in covered and ln not in skel]
    rt_bad = [a for a, (s, e) in r1.anchors.items() if r1.expand(a) != "\n".join(lines[s - 1:e])]
    bounds_bad = [a for a, (s, e) in r1.anchors.items() if not (1 <= s <= e <= len(lines))]
    recon = r1.full_text == disk
    return {
        "path": path,
        "lines": len(lines),
        "anchors": len(r1.anchors),
        "lost": lost,
        "roundtrip_bad": rt_bad,
        "bounds_bad": bounds_bad,
        "reconstruction_exact": recon,
        "deterministic": r1.skeleton == r2.skeleton,
        "ok": not lost and not rt_bad and not bounds_bad and recon and r1.skeleton == r2.skeleton,
    }


def check_source(source: str, suffix: str = ".py") -> dict:
    """Check an in-memory source string by writing it to a temp file."""
    import tempfile
    fd, p = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", errors="replace") as f:
            f.write(source)
        return check_file(p)
    finally:
        os.unlink(p)


def _fail_reasons(v: dict) -> str:
    reasons = []
    if v["lost"]:
        reasons.append(f"{len(v['lost'])} unrecoverable line(s): {v['lost'][:8]}")
    if v["roundtrip_bad"]:
        reasons.append(f"round-trip mismatch on {v['roundtrip_bad'][:8]}")
    if v["bounds_bad"]:
        reasons.append(f"out-of-bounds anchors {v['bounds_bad'][:8]}")
    if not v["reconstruction_exact"]:
        reasons.append("reconstruction differs from the file on disk")
    if not v["deterministic"]:
        reasons.append("two skims produced different skeletons")
    return "; ".join(reasons)


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="skim-verify",
        description="Verify skim's five lossless invariants against your own files.",
    )
    ap.add_argument("paths", nargs="+", help="files to check (directories are not walked; use a glob)")
    ap.add_argument("--json", action="store_true", help="print one JSON verdict per line instead of text")
    args = ap.parse_args(argv)

    worst = 0
    verdicts = []
    for path in args.paths:
        if os.path.isdir(path):
            verdicts.append({"path": path, "ok": False, "crash": "is a directory; pass files (use a glob)"})
            worst = max(worst, 2)
            continue
        try:
            v = check_file(path)
        except Exception as ex:  # NO-CRASH violation (or unreadable path)
            verdicts.append({"path": path, "ok": False, "crash": repr(ex)})
            worst = max(worst, 2)
            continue
        verdicts.append(v)
        if not v["ok"]:
            worst = max(worst, 1)

    for v in verdicts:
        if args.json:
            print(json.dumps(v))
        elif "crash" in v:
            print(f"CRASH {v['path']}  {v['crash']}")
        elif v["ok"]:
            print(f"PASS  {v['path']}  ({v['lines']:,} lines, {v['anchors']} anchors, "
                  f"reconstruction exact, deterministic)")
        else:
            print(f"FAIL  {v['path']}  {_fail_reasons(v)}")
    if not args.json and len(verdicts) > 1:
        ok = sum(1 for v in verdicts if v.get("ok"))
        print(f"\n{ok}/{len(verdicts)} files pass all five invariants")
    return worst


if __name__ == "__main__":
    sys.exit(main())
