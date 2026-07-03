"""Shared invariant checker for the test suite."""
import os
import tempfile

from skim import skim_file


def run_invariants(source: str, suffix: str = ".py") -> dict:
    fd, p = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", errors="replace") as f:
            f.write(source)
        r1 = skim_file(p)
        r2 = skim_file(p)
        with open(p, encoding="utf-8", errors="replace") as f:
            disk = f.read()                       # exactly what skim_file decoded
        lines = r1._lines
        covered = set()
        for s, e in r1.anchors.values():
            covered.update(range(s, e + 1))
        skel = set(r1.skeleton.split("\n"))       # skeleton is joined with "\n"; split the same way
        lost = [i for i, ln in enumerate(lines, 1) if ln.strip() and i not in covered and ln not in skel]
        rt = [a for a, (s, e) in r1.anchors.items() if r1.expand(a) != "\n".join(lines[s - 1:e])]
        bounds = [a for a, (s, e) in r1.anchors.items() if not (1 <= s <= e <= len(lines))]
        return {"lost": lost, "rt": rt, "bounds": bounds,
                "recon": r1.full_text == disk,    # byte-exact reconstruction of the decoded source
                "det": r1.skeleton == r2.skeleton, "anchors": len(r1.anchors), "result": r1}
    finally:
        os.unlink(p)


def assert_airtight(source: str, suffix: str = ".py") -> dict:
    v = run_invariants(source, suffix)
    assert v["lost"] == [], f"LOSSLESS violated, unrecoverable lines: {v['lost']}"
    assert v["rt"] == [], f"ROUND-TRIP violated, bad anchors: {v['rt']}"
    assert v["bounds"] == [], f"BOUNDS violated, anchors: {v['bounds']}"
    assert v["recon"], "RECONSTRUCTION violated: full_text != decoded file content"
    assert v["det"], "DETERMINISM violated, skeleton differs across runs"
    return v
