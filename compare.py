"""Head-to-head: skim vs the existing approaches, same files, real tokens.

  skim                 -> our skeleton (lossless, lazy-expandable)
  signatures-only      -> faithful repro of the Aider/Basemind/Repomix mechanism
                          (tree-sitter-style: keep signatures, DROP bodies/docstrings/comments,
                          NOT recoverable). Reproduced with ast since Basemind needs Rust (no cargo here).
  full read            -> what Claude's Read tool ingests today (the 100% baseline)

Also copies the same files into a corpus dir so Repomix --compress can be run on the identical set:
  uv run python compare.py <corpus_dir> <n>
  npx -y repomix <corpus_dir> --compress --style plain --output <corpus_dir>/repomix_out.txt
  uv run python compare.py --count <corpus_dir>/repomix_out.txt
"""
import ast
import glob
import os
import shutil
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
from skim import skim_file, count_tokens  # noqa: E402


def collect(n=30, min_bytes=1500):
    libdir = os.path.dirname(os.__file__)
    files = [f for f in sorted(glob.glob(os.path.join(libdir, "*.py")))
             if os.path.getsize(f) >= min_bytes]
    files.sort(key=os.path.getsize)
    if len(files) > n:
        step = len(files) / n
        files = [files[int(i * step)] for i in range(n)]
    return files


def signatures_only(path):
    """Aider/Basemind/Repomix-style: signatures + structure only, bodies/docstrings/comments gone."""
    src = open(path, encoding="utf-8", errors="replace").read()
    lines = src.splitlines()
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src
    out = []

    def sig(node, indent):
        hs = min([node.lineno] + [d.lineno for d in node.decorator_list])
        bs = node.body[0].lineno
        if bs > hs:
            out.extend((indent + x.strip() if indent else x) for x in lines[hs - 1:bs - 1])
        else:
            out.append((indent + lines[hs - 1].strip()) if indent else lines[hs - 1])

    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            out.extend(lines[node.lineno - 1:node.end_lineno])
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            out.append(lines[node.lineno - 1])           # constant name line (no multi-line value)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            sig(node, "")
        elif isinstance(node, ast.ClassDef):
            hs = min([node.lineno] + [d.lineno for d in node.decorator_list])
            bs = node.body[0].lineno
            out.extend(lines[hs - 1:bs - 1] if bs > hs else [lines[hs - 1]])
            for m in node.body:
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    sig(m, "    ")
    return "\n".join(out)


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == "--count":
        text = open(sys.argv[2], encoding="utf-8", errors="replace").read()
        print(f"{sys.argv[2]}: {count_tokens(text)} tokens")
        return

    corpus_dir = sys.argv[1] if len(sys.argv) > 1 else "bench_corpus"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    files = collect(n)
    os.makedirs(corpus_dir, exist_ok=True)
    for old in glob.glob(os.path.join(corpus_dir, "*.py")):
        os.remove(old)

    tot = {"full": 0, "skim": 0, "sig": 0}
    for i, f in enumerate(files):
        content = open(f, encoding="utf-8", errors="replace").read()
        shutil.copy(f, os.path.join(corpus_dir, f"{i:02d}_{os.path.basename(f)}"))
        tot["full"] += count_tokens(content)
        tot["skim"] += count_tokens(skim_file(f).skeleton)
        tot["sig"] += count_tokens(signatures_only(f))

    fu = tot["full"]
    print(f"corpus: {len(files)} real stdlib files -> {os.path.abspath(corpus_dir)}\n")
    print(f"{'method':<34}{'tokens':>9}{'% of full':>11}  recoverable?")
    print(f"{'full read (Claude Read tool)':<34}{tot['full']:>9}{100.0:>10.1f}%  yes (100%)")
    print(f"{'skim skeleton':<34}{tot['skim']:>9}{100*tot['skim']/fu:>10.1f}%  YES (100%, lazy expand)")
    print(f"{'signatures-only (Aider/Basemind)':<34}{tot['sig']:>9}{100*tot['sig']/fu:>10.1f}%  NO (bodies/comments gone)")
    print(f"\nNext: npx -y repomix \"{os.path.abspath(corpus_dir)}\" --compress --style plain "
          f"--output \"{os.path.join(os.path.abspath(corpus_dir), 'repomix_out.txt')}\"")


if __name__ == "__main__":
    main()
