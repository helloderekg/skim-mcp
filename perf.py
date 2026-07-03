"""Performance benchmark: throughput, scaling (should be ~linear), and memory.

    uv run python perf.py
"""
import os
import sys
import tempfile
import time
import tracemalloc

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from skim import skim_file  # noqa: E402


def make_py(nfuncs: int) -> str:
    return "\n".join(
        f"def func_{i}(a, b, c):\n    '''doc {i}'''\n    x = a + b * c\n"
        f"    if x > {i}:\n        return x\n    return {i}\n"
        for i in range(nfuncs)
    )


def _best_ms(path: str, reps: int = 3) -> float:
    best = float("inf")
    for _ in range(reps):
        t = time.perf_counter()
        skim_file(path)
        best = min(best, (time.perf_counter() - t) * 1000)
    return best


def timeit(source: str, suffix: str):
    fd, p = tempfile.mkstemp(suffix=suffix)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(source)
    try:
        return source.count("\n") + 1, _best_ms(p)
    finally:
        os.unlink(p)


print(f"{'lines':>9}{'ms':>9}{'ms / 1k lines':>15}   (Python ast path)")
prev = None
for n in (250, 1250, 5000):
    nlines, ms = timeit(make_py(n), ".py")
    print(f"{nlines:>9}{ms:>9.1f}{ms / nlines * 1000:>15.2f}")
    prev = (nlines, ms)

log = "\n".join(
    f"2026-06-28T10:{i // 60 % 60:02d}:{i % 60:02d} INFO request {i} took {i % 100}ms code 200"
    for i in range(100_000)
)
nlines, ms = timeit(log, ".log")
print(f"\n100k-line log (generic path): {ms:.0f} ms ({ms / nlines * 1000:.2f} ms / 1k lines)")

tracemalloc.start()
fd, p = tempfile.mkstemp(suffix=".py")
with os.fdopen(fd, "w", encoding="utf-8") as f:
    f.write(make_py(5000))
skim_file(p)
os.unlink(p)
_, peak = tracemalloc.get_traced_memory()
tracemalloc.stop()
print(f"peak python-heap on ~30k-line file: {peak / 1e6:.1f} MB")
