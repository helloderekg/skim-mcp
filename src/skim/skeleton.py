"""skim core - turn a large source into a compact skeleton + byte-exact expand anchors.

Two paths:
  * Python  -> structural skeleton via `ast` (signatures + docstring line + collapsed bodies).
              (Code skeletonization is table-stakes: Aider/Basemind already ship it. We include
               it so the tool is useful on code, not because it's novel.)
  * Anything else -> block outline with the two real differentiators:
      - RETENTION: critical literals (numbers, error codes, paths, negations) are PROMOTED into
        the skeleton so a collapsed span never hides a load-bearing value.
      - DEDUP: byte-identical blocks collapse to a pointer ("identical to a3") instead of repeating.

Every collapsed region becomes an anchor -> exact (start_line, end_line). `expand` returns the
original bytes verbatim. A coverage-completion sweep guarantees every non-blank original line is
either shown in the skeleton or reachable through an anchor, so compression is LAZY, never LOSSY.
"""
from __future__ import annotations
import ast
import hashlib
import os
from dataclasses import dataclass, field

from .tokens import count_tokens
from .retain import critical_hits
from .templater import log_templates

_EXT_LANG = {
    ".py": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript", ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "tsx",
    ".go": "go", ".rs": "rust", ".java": "java", ".rb": "ruby",
    ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp",
    ".cs": "csharp", ".php": "php", ".kt": "kotlin", ".swift": "swift", ".scala": "scala",
    ".sh": "bash", ".bash": "bash", ".lua": "lua", ".r": "r",
    ".json": "json", ".ndjson": "ndjson", ".csv": "csv", ".log": "log",
    ".md": "markdown", ".txt": "text", ".yaml": "yaml", ".yml": "yaml", ".sql": "sql",
}

# Languages handled by the tree-sitter path (label -> tree-sitter-language-pack grammar name).
# Optional: requires `tree-sitter` + `tree-sitter-language-pack` (pip install skim-mcp[lang]).
# Falls back to the generic path if not installed or on any parse failure.
_TS_LANGS = {
    "javascript": "javascript", "typescript": "typescript", "tsx": "tsx", "go": "go",
    "rust": "rust", "java": "java", "c": "c", "cpp": "cpp", "ruby": "ruby",
    "csharp": "csharp", "php": "php", "kotlin": "kotlin", "swift": "swift", "scala": "scala",
    "bash": "bash", "lua": "lua", "r": "r",
}


def _lang_for(path: str) -> str:
    low = path.lower()
    for ext, lang in _EXT_LANG.items():
        if low.endswith(ext):
            return lang
    return "text"


def _lines_of(source: str) -> list:
    # split("\n"), NOT str.splitlines(): splitlines also breaks on \v \f \x1c-\x1e \x85
    # (see the table in the Python docs for str.splitlines). Here those are CONTENT, not line endings -
    # open()/subprocess text mode already normalized \r\n and \r to \n (universal newlines). Splitting
    # on "\n" alone keeps ast/tree-sitter line numbers aligned with our indices and makes
    # "\n".join(lines) reconstruct the decoded source EXACTLY, which the test suite enforces.
    return source.split("\n")


@dataclass
class SkimResult:
    path: str
    language: str
    skeleton: str
    anchors: dict                         # aid -> (start_line, end_line), 1-based inclusive
    _lines: list = field(default_factory=list, repr=False)

    @property
    def full_text(self) -> str:
        return "\n".join(self._lines)

    def expand(self, aid: str) -> str:
        """Return the exact original lines for an anchor. Lossless."""
        if aid not in self.anchors:
            raise KeyError(f"unknown anchor {aid!r}; known: {', '.join(self.anchors) or '(none)'}")
        s, e = self.anchors[aid]
        return "\n".join(self._lines[s - 1:e])

    def report(self) -> dict:
        ft = count_tokens(self.full_text)
        st = count_tokens(self.skeleton)
        return {
            "path": self.path,
            "language": self.language,
            "full_lines": len(self._lines),
            "full_tokens": ft,
            "skeleton_tokens": st,
            "anchors": len(self.anchors),
            "ratio": round(ft / max(1, st), 1),
            "saved_pct": round(100 * (1 - st / max(1, ft)), 1),
        }


def skim_file(path: str) -> SkimResult:
    if not os.path.isfile(path):                       # directories / missing -> clean error, never a raw OSError
        raise ValueError(f"not a readable file: {path}")
    with open(path, "rb") as fb:                       # git's binary heuristic: NUL in the first 8000 bytes
        binary = b"\0" in fb.read(8000)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        source = f.read()
    lang = _lang_for(path)
    if not binary:
        if lang == "python":
            try:
                return _skim_python(path, source)
            except (SyntaxError, ValueError, RecursionError):
                pass  # unparseable / null-bytes / pathologically deep -> generic path (never crash)
        elif lang in _TS_LANGS:
            try:
                return _skim_treesitter(path, source, lang)
            except Exception:
                pass  # tree-sitter not installed, or a parse failure -> generic path (never crash)
    r = _skim_generic(path, source, lang)
    if binary:
        # still lossless w.r.t. the DECODED text, but say so - a model reading garbage should know why
        r.skeleton = ("# [skim] NUL bytes detected (binary file?) - this text view uses replacement "
                      "characters and is not byte-faithful\n") + r.skeleton
    return r


def skim_text(text: str, language: str = "log", path: str = "<text>") -> SkimResult:
    """Skim an in-memory string (e.g. captured command output) via the generic path. Lossless."""
    return _skim_generic(path, text, language)


# ----- Python (structural, via ast) -----------------------------------------

def _is_doc(stmt) -> bool:
    return (isinstance(stmt, ast.Expr)
            and isinstance(getattr(stmt, "value", None), ast.Constant)
            and isinstance(stmt.value.value, str))


def _doc1(node) -> str | None:
    body = getattr(node, "body", None)
    if body and _is_doc(body[0]):
        d = body[0].value.value.strip().splitlines()
        return d[0].strip() if d else ""
    return None


def _skim_python(path: str, source: str) -> SkimResult:
    lines = _lines_of(source)
    tree = ast.parse(source)
    out: list[str] = []
    anchors: dict = {}
    covered: set[int] = set()              # original line numbers shown verbatim or anchored
    ctr = [0]

    def mark(s: int, e: int) -> None:
        if e >= s:
            covered.update(range(s, e + 1))

    def anchor(s: int, e: int) -> str:
        ctr[0] += 1
        aid = f"a{ctr[0]}"
        anchors[aid] = (s, e)
        mark(s, e)
        return aid

    def emit_callable(node, indent: str) -> None:
        decs = [d.lineno for d in node.decorator_list]
        hstart = min([node.lineno] + decs)
        bstart = node.body[0].lineno
        bend = node.end_lineno
        if bstart <= node.lineno:                  # body begins on the def line
            out.extend(lines[hstart - 1:node.lineno])   # decorators + def line (keeps the signature) verbatim
            mark(hstart, node.lineno)
            if bend > node.lineno:                 # body continues onto later lines -> collapse them as a body
                aid = anchor(node.lineno + 1, bend)
                out.append(f'{indent}    # ... {bend - node.lineno} more line(s) -> expand("{aid}")')
            return
        out.extend(lines[hstart - 1:bstart - 1])   # decorators + (possibly multi-line) signature, verbatim
        mark(hstart, bstart - 1)
        d1 = _doc1(node)
        if d1:
            out.append(f"{indent}    # [doc] {d1}")
        aid = anchor(bstart, bend)
        out.append(f'{indent}    # ... {bend - bstart + 1} line body -> expand("{aid}")')

    body = tree.body
    idx = 0
    md = ast.get_docstring(tree)
    if md and body and _is_doc(body[0]):
        out.append(f'"""{md.strip().splitlines()[0]} ..."""')   # synthesized first line for context
        idx = 1                                                  # full docstring recovered by the sweep

    for node in body[idx:]:
        try:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                out.extend(lines[node.lineno - 1:node.end_lineno])
                mark(node.lineno, node.end_lineno)
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                span = lines[node.lineno - 1:node.end_lineno]
                if len(span) <= 3:
                    out.extend(span)
                    mark(node.lineno, node.end_lineno)
                else:
                    out.append(span[0])
                    mark(node.lineno, node.lineno)
                    aid = anchor(node.lineno + 1, node.end_lineno)
                    out.append(f'    # ... {len(span) - 1} more -> expand("{aid}")')
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                emit_callable(node, "")
                out.append("")
            elif isinstance(node, ast.ClassDef):
                decs = [d.lineno for d in node.decorator_list]
                hstart = min([node.lineno] + decs)
                bstart = node.body[0].lineno
                out.extend(lines[hstart - 1:bstart - 1])
                mark(hstart, bstart - 1)
                d1 = _doc1(node)
                if d1:
                    out.append(f"    # [doc] {d1}")
                cidx = 1 if _is_doc(node.body[0]) else 0
                for m in node.body[cidx:]:
                    if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        emit_callable(m, "    ")
                    elif isinstance(m, (ast.Assign, ast.AnnAssign)):
                        span = lines[m.lineno - 1:m.end_lineno]
                        if len(span) <= 2:
                            out.extend(span)
                            mark(m.lineno, m.end_lineno)
                        else:
                            out.append(span[0])
                            mark(m.lineno, m.lineno)
                            aid = anchor(m.lineno + 1, m.end_lineno)
                            out.append(f'        # ... {len(span) - 1} more -> expand("{aid}")')
                    else:
                        s, e = m.lineno, m.end_lineno
                        out.append("    " + lines[s - 1].strip())
                        aid = anchor(s, e)
                        out.append(f'        # ... {e - s + 1} line block -> expand("{aid}")')
                out.append("")
            else:
                s, e = node.lineno, node.end_lineno
                if e - s <= 2:
                    out.extend(lines[s - 1:e])
                    mark(s, e)
                else:
                    out.append(lines[s - 1])
                    mark(s, s)
                    aid = anchor(s + 1, e)
                    out.append(f'# ... {e - s} more -> expand("{aid}")')
        except Exception:
            s = getattr(node, "lineno", 1)
            e = getattr(node, "end_lineno", s)
            if s - 1 < len(lines):
                out.append(lines[s - 1])
                mark(s, s)
            if e > s:
                aid = anchor(s + 1, e)
                out.append(f'# ... {e - s} more -> expand("{aid}")')

    # Coverage-completion sweep: any non-blank original line not shown verbatim and not in an anchor
    # (standalone comments, module-docstring tails, anything ast omits) becomes a gap anchor, so
    # EVERY original line is recoverable -> true lossless lazy expansion.
    significant = [i for i, ln in enumerate(lines, start=1) if ln.strip()]
    missing = sorted(set(significant) - covered)
    if missing:
        groups, gs, pe = [], missing[0], missing[0]
        for ln in missing[1:]:
            if ln == pe + 1:
                pe = ln
            else:
                groups.append((gs, pe))
                gs = pe = ln
        groups.append((gs, pe))
        out.append("# --- unshown spans (comments / docstring text), recoverable ---")
        for gs, ge in groups:
            aid = anchor(gs, ge)
            out.append(f'# ... {ge - gs + 1} line(s) [L{gs}-{ge}] -> expand("{aid}")')

    return SkimResult(path, "python", "\n".join(out), anchors, lines)


# ----- Tree-sitter (multi-language, structural) -----------------------------
# Node kinds verified against real parses of each grammar (not memory).
_TS_FUNC = {
    "function_declaration", "function_definition", "function_item", "method_definition",
    "method_declaration", "method", "singleton_method", "constructor_declaration",
    "local_function_statement", "generator_function_declaration", "function_expression",
}
_TS_BRACE_BODY = {"statement_block", "block", "compound_statement",
                  "braced_expression"}                                # braced_expression: R; braces on own lines
_TS_BODY = _TS_BRACE_BODY | {"body_statement", "function_body"}       # body_statement (Ruby) has no braces
_TS_NOBRACE_OVERRIDE = {("lua", "block")}   # lua's "block" has no braces (unlike rust/java "block")


def _tsc(x):
    """This grammar binding exposes node accessors as methods; call them (or read, if a property)."""
    return x() if callable(x) else x


def _tsrow(p):
    p = _tsc(p)
    return p.row if hasattr(p, "row") else p[0]


def _skim_treesitter(path: str, source: str, lang: str) -> SkimResult:
    from tree_sitter_language_pack import get_parser   # optional dep; ImportError -> caller falls back

    parser = get_parser(_TS_LANGS[lang])
    root = _tsc(parser.parse(source).root_node)
    lines = _lines_of(source)

    collapsed = []   # (start_line, end_line) 1-based inclusive — function bodies to fold

    def body_of(node):
        last = None
        for i in range(_tsc(node.child_count)):
            c = node.child(i)
            if _tsc(c.kind) in _TS_BODY:
                last = c
        return last

    def visit(node):
        if _tsc(node.kind) in _TS_FUNC:
            b = body_of(node)
            if b is not None:
                bs = _tsrow(b.start_position) + 1
                be = _tsrow(b.end_position) + 1
                kind = _tsc(b.kind)
                if kind in _TS_BRACE_BODY and (lang, kind) not in _TS_NOBRACE_OVERRIDE:
                    cs, ce = bs + 1, be - 1      # keep the `{` and `}` lines, fold the interior
                else:
                    cs, ce = bs, be              # no braces (Ruby, Lua): fold the whole body
                if ce >= cs:
                    collapsed.append((cs, ce))
                return                            # don't recurse into a folded function
        for i in range(_tsc(node.child_count)):
            visit(node.child(i))

    visit(root)
    collapsed.sort()
    merged = []
    for s, e in collapsed:
        if merged and s <= merged[-1][1]:
            continue                              # defensive: drop any nested/overlapping range
        merged.append((s, e))

    out, anchors, covered = [], {}, set()
    ctr = [0]

    def anchor(s, e):
        ctr[0] += 1
        aid = f"a{ctr[0]}"
        anchors[aid] = (s, e)
        covered.update(range(s, e + 1))
        return aid

    i, ci, n = 1, 0, len(lines)
    while i <= n:
        if ci < len(merged) and merged[ci][0] == i:
            s, e = merged[ci]
            ci += 1
            aid = anchor(s, e)
            out.append(f'# ... {e - s + 1} line body -> expand("{aid}")')
            i = e + 1
        else:
            out.append(lines[i - 1])
            covered.add(i)
            i += 1

    # Coverage-completion sweep: same lossless guarantee as the other paths.
    significant = [k for k, ln in enumerate(lines, 1) if ln.strip()]
    missing = sorted(set(significant) - covered)
    if missing:
        groups, gs, pe = [], missing[0], missing[0]
        for ln in missing[1:]:
            if ln == pe + 1:
                pe = ln
            else:
                groups.append((gs, pe))
                gs = pe = ln
        groups.append((gs, pe))
        out.append("# --- unshown spans, recoverable ---")
        for gs, ge in groups:
            aid = anchor(gs, ge)
            out.append(f'# ... {ge - gs + 1} line(s) [L{gs}-{ge}] -> expand("{aid}")')

    return SkimResult(path, lang, "\n".join(out), anchors, lines)


# ----- Generic (blocks + retention + dedup) ---------------------------------

def _skim_generic(path: str, source: str, lang: str) -> SkimResult:
    lines = _lines_of(source)
    out: list[str] = []
    anchors: dict = {}
    covered: set[int] = set()
    seen_hash: dict = {}        # block hash -> anchor id (dedup)
    ctr = [0]

    def anchor(s: int, e: int) -> str:
        ctr[0] += 1
        aid = f"a{ctr[0]}"
        anchors[aid] = (s, e)
        covered.update(range(s, e + 1))
        return aid

    i, n = 0, len(lines)
    while i < n:
        if not lines[i].strip():
            i += 1
            continue
        start = i
        j = i
        while j < n and lines[j].strip():
            j += 1
        block = lines[start:j]
        out.append(block[0])                # first line of the block, verbatim
        covered.add(start + 1)
        if len(block) > 1:
            h = hashlib.sha1("\n".join(block).encode("utf-8", "replace")).hexdigest()
            if h in seen_hash:
                aid = anchor(start + 2, j)   # dedup: still anchor THIS block's lines so it stays recoverable
                out.append(f'#   ... identical to {seen_hash[h]} ({len(block)} lines) -> expand("{aid}")')
            else:
                aid = anchor(start + 2, j)
                seen_hash[h] = aid
                hits = critical_hits("\n".join(block[1:])[:20000])  # bound the scan on huge blocks
                note = f"   keeps: {', '.join(hits)}" if hits else ""
                out.append(f'#   ... {len(block) - 1} more line(s) -> expand("{aid}"){note}')
                if len(block) > 40:                     # dense block: show WHAT repeats (Drain-style)
                    tpls, ntpl = log_templates(block[1:2000])
                    for count, tpl, first in tpls:
                        out.append(f"#     ~{count}x  {tpl[:160]}")
                    if ntpl > len(tpls) and tpls:
                        out.append(f"#     (+{ntpl - len(tpls)} more repeated shapes in this block)")
        i = j

    # Coverage-completion sweep: the same lossless guarantee the python path has, so no block logic
    # (e.g. dedup) can ever drop a line.
    significant = [k for k, ln in enumerate(lines, start=1) if ln.strip()]
    missing = sorted(set(significant) - covered)
    if missing:
        groups, gs, pe = [], missing[0], missing[0]
        for ln in missing[1:]:
            if ln == pe + 1:
                pe = ln
            else:
                groups.append((gs, pe))
                gs = pe = ln
        groups.append((gs, pe))
        out.append("# --- unshown spans, recoverable ---")
        for gs, ge in groups:
            aid = anchor(gs, ge)
            out.append(f'# ... {ge - gs + 1} line(s) [L{gs}-{ge}] -> expand("{aid}")')

    return SkimResult(path, lang, "\n".join(out), anchors, lines)
