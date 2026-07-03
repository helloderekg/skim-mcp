"""Measure skim across a large real corpus: token savings, stability, correctness, speed.

    uv run python bench.py

Corpus = the running interpreter's standard library (real, diverse, varying sizes).
Reports: ratio distribution, overall weighted savings, determinism (same file x5),
anchor-bounds validity, losslessness coverage (is any original line unrecoverable?),
crashes, and timing.
"""
import glob
import hashlib
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from skim import skim_file, token_basis  # noqa: E402


def collect(limit=80, min_bytes=1200):
    libdir = os.path.dirname(os.__file__)                       # stdlib of this interpreter
    files = sorted(glob.glob(os.path.join(libdir, "*.py")))
    for sub in ("json", "email", "collections", "http", "importlib", "asyncio"):
        files += sorted(glob.glob(os.path.join(libdir, sub, "*.py")))
    out, seen = [], set()
    for f in files:
        if f in seen:
            continue
        seen.add(f)
        try:
            if os.path.getsize(f) >= min_bytes:
                out.append(f)
        except OSError:
            pass
    # spread across sizes rather than taking only the alphabetic head
    out.sort(key=lambda p: os.path.getsize(p))
    if len(out) > limit:
        step = len(out) / limit
        out = [out[int(i * step)] for i in range(limit)]
    return out


def coverage_loss(r):
    """Count original non-blank lines that are NEITHER inside an anchor NOR verbatim in the skeleton
    (i.e. silently unrecoverable). 0 = every line is either shown or expandable."""
    covered = set()
    for s, e in r.anchors.values():
        covered.update(range(s, e + 1))
    skel = set(r.skeleton.split("\n"))
    lost = 0
    for i, line in enumerate(r._lines, start=1):
        if i in covered or not line.strip():
            continue
        if line not in skel:
            lost += 1
    return lost


def main():
    files = collect()
    print(f"token basis: {token_basis()}")
    print(f"corpus: {len(files)} real files from the stdlib\n")

    rows, failures = [], []
    bounds_bad = 0
    total_lost = 0
    total_sig = 0
    t0 = time.time()
    for f in files:
        try:
            r = skim_file(f)
            rep = r.report()
            for s, e in r.anchors.values():                     # bounds validity
                if not (1 <= s <= e <= len(r._lines)):
                    bounds_bad += 1
            total_lost += coverage_loss(r)
            total_sig += sum(1 for ln in r._lines if ln.strip())
            rep["_path"] = f
            rows.append(rep)
        except Exception as ex:                                  # robustness
            failures.append((f, repr(ex)))
    elapsed = time.time() - t0

    # determinism: same file x5 -> identical skeleton + token count
    nondet = []
    for f in files[:15]:
        sigs, toks = set(), set()
        for _ in range(5):
            rr = skim_file(f)
            sigs.add(hashlib.sha1(rr.skeleton.encode("utf-8", "replace")).hexdigest())
            toks.add(rr.report()["skeleton_tokens"])
        if len(sigs) != 1 or len(toks) != 1:
            nondet.append(os.path.basename(f))

    ratios = [x["ratio"] for x in rows]
    full = sum(x["full_tokens"] for x in rows)
    skel = sum(x["skeleton_tokens"] for x in rows)
    q = statistics.quantiles(ratios, n=4)

    print(f"processed {len(rows)} files in {elapsed * 1000:.0f} ms "
          f"({elapsed * 1000 / max(1, len(rows)):.2f} ms/file)")
    print(f"crashes:                 {len(failures)}")
    print(f"anchor-bounds errors:    {bounds_bad}")
    print(f"determinism (x5, 15 files): {'STABLE (identical every run)' if not nondet else 'NONDETERMINISTIC: ' + str(nondet)}")
    print(f"losslessness: {total_lost} of {total_sig} non-blank lines unrecoverable "
          f"({100 * (1 - total_lost / max(1, total_sig)):.2f}% recoverable)")
    print()
    print("per-file compression ratio (full_tokens / skeleton_tokens):")
    print(f"  min {min(ratios):.1f}   p25 {q[0]:.1f}   median {statistics.median(ratios):.1f}   "
          f"mean {statistics.mean(ratios):.1f}   p75 {q[2]:.1f}   max {max(ratios):.1f}   "
          f"stdev {statistics.pstdev(ratios):.2f}")
    print(f"overall weighted: {full / skel:.2f}x  ({full:,} -> {skel:,} tokens, "
          f"{100 * (1 - skel / full):.1f}% saved)")
    print()
    rs = sorted(rows, key=lambda x: x["ratio"])
    print("least compressible:")
    for x in rs[:3]:
        print(f"  {x['ratio']:.1f}x  {os.path.basename(x['_path']):<22} {x['full_lines']:>5} lines  {x['full_tokens']:>6} tok")
    print("most compressible:")
    for x in rs[-3:]:
        print(f"  {x['ratio']:.1f}x  {os.path.basename(x['_path']):<22} {x['full_lines']:>5} lines  {x['full_tokens']:>6} tok")
    if failures:
        print("\nFAILURES:")
        for f, ex in failures[:10]:
            print("  ", os.path.basename(f), ex)


if __name__ == "__main__":
    main()
