"""skim MCP server - skim-then-expand reader for Claude Code / desktop Claude.

Six tools (skim_open, skim_expand, skim_search, skim_run, skim_repo, skim_patch). The skeleton is the only
thing that normally lands in context; every detailed span is pulled on demand. Tool results count
against the model's context exactly like text
(Claude Code warns >10k tokens, hard-caps ~25k), so skim_open keeps the skeleton small and
hands back anchor ids the model expands only when it needs them.

Every tool call is logged to skim_calls.jsonl so the expand-loop can be MEASURED (does the model
actually call skim_expand when the answer needs a hidden span?). The skeleton carries an explicit
steering line to reduce under-fetch - both are research-backed: Anthropic's tool-writing guidance
says truncated results should steer the agent with actionable hints, and the under-fetch failure
mode (answering confidently from insufficient context) is the one risk that can sink the product.
"""
from __future__ import annotations
import json
import os
import re
import signal
import time
import uuid
import hashlib
import subprocess
from collections import OrderedDict

from mcp.server.fastmcp import FastMCP

from .skeleton import skim_file, skim_text, SkimResult
from .tokens import count_tokens
from .logpath import default_log_path

INSTRUCTIONS = (
    "skim reads large files, logs, and whole repos with far fewer context tokens, losslessly. "
    "DEFAULT TO skim instead of the built-in Read/Bash whenever you are about to read a file over "
    "~300 lines, scan a directory or repo, or run a verbose command (tests, builds, npm/pip, big "
    "logs): it returns a compact skeleton and lets you expand the exact spans you need, so it is "
    "strictly cheaper with no loss of information. "
    "skim_open(path) returns a compact SKELETON (code structure + signatures; for logs/data, "
    "critical values like ids, numbers, dates, paths, and error codes are preserved) plus anchor "
    "ids and a token report. Read the skeleton, then skim_expand(handle, anchors=[...]) returns ONLY "
    "the exact spans you need, verbatim and lossless. skim_search(handle, query) finds which anchors "
    "contain a string. skim_run(command) runs a shell command and returns a compact, expandable view of "
    "its output - use it for verbose commands instead of dumping the full output. "
    "skim_repo(path, query) maps a WHOLE repo/directory: ranked file skeletons within a token budget, "
    "each expandable to exact code - use it to understand a codebase before diving in. "
    "skim_patch(handle, anchor, new_text) replaces exactly one expanded span on disk - because expands "
    "are verbatim, the edit is drift-safe: it is refused if the file changed since skim_open. "
    "IMPORTANT: collapsed bodies are NOT in the skeleton - if an answer needs a body, expand it; "
    "do not answer from the skeleton alone when the detail lives in a collapsed span."
)

# Steering line prepended to every skeleton - the cheap, research-backed under-fetch mitigation.
_STEER = (
    '# skim: COMPACT skeleton - bodies are collapsed behind anchors like expand("a7"). '
    "If the answer needs a collapsed body or hidden value, call skim_expand(handle, anchors=[...]); "
    "do NOT answer from the skeleton alone when a body is required. "
    "Use skim_search(handle, query) to find which anchor holds a value."
)

mcp = FastMCP("skim", instructions=INSTRUCTIONS)

_SESSIONS: OrderedDict[str, SkimResult] = OrderedDict()
# Bounded LRU: each entry holds a file's full lines, and a session can map hundreds of files.
# 512 comfortably covers a skim_repo sweep + a long session; evicted handles fail with the same
# clean "unknown handle" error as a restart (just re-open). Override with SKIM_MAX_HANDLES.
_SESSIONS_MAX = max(8, int(os.environ.get("SKIM_MAX_HANDLES") or 512))
_SKELETON_TOKEN_SOFTCAP = 8000  # keep skim_open under Claude Code's 10k-token warning line


def _remember(handle: str, r: SkimResult) -> None:
    _SESSIONS[handle] = r
    _SESSIONS.move_to_end(handle)
    while len(_SESSIONS) > _SESSIONS_MAX:
        _SESSIONS.popitem(last=False)


def _recall(handle: str) -> SkimResult | None:
    r = _SESSIONS.get(handle)
    if r is not None:
        _SESSIONS.move_to_end(handle)   # recently used stays alive
    return r

# Instrumentation: append-only JSONL of every tool call, for measuring the expand-loop.
_LOG_FILE = default_log_path()
try:
    os.makedirs(os.path.dirname(_LOG_FILE), exist_ok=True)   # ~/.skim/ may not exist yet
except OSError:
    pass  # unwritable location just means no instrumentation, never a broken server

# One id per server PROCESS. Claude Code's stdio transport spawns a separate skim process per session,
# so this id is effectively per-session and lets the meter break savings down by session. Override the
# label with SKIM_SESSION_LABEL when you launch a dedicated instance (e.g. a specific agent/worktree).
# NOTE: MCP does not tell the server which sub-agent issued a call, so granularity finer than the
# per-connection process (this id) is not available server-side.
_SESSION_ID = os.environ.get("SKIM_SESSION_LABEL") or uuid.uuid4().hex[:8]
_SESSION_META = {"id": _SESSION_ID, "named": bool(os.environ.get("SKIM_SESSION_LABEL")),
                 "cwd": os.getcwd(), "pid": os.getpid(), "started": round(time.time(), 3)}


def _log(event: dict) -> None:
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": round(time.time(), 3), "session": _SESSION_ID, **event},
                               ensure_ascii=False) + "\n")
    except Exception:
        pass  # logging must never break a tool call


def _kill_tree(proc: subprocess.Popen) -> None:
    # taskkill /T "ends the specified process and any child processes started by it" (MS docs);
    # on POSIX the child got its own session (start_new_session), so the group signal takes the tree.
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, timeout=10)
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()                        # last resort: at least the direct child dies
        except Exception:
            pass


def _handle_for(path: str, content: str) -> str:
    # The digest covers CONTENT, not just the path: re-opening a changed file (or re-running a
    # command with different output) mints a NEW handle, while the old handle keeps resolving
    # against its own snapshot. Anchor ids therefore can never silently point at different lines.
    # Identical content collides on purpose - skimming is deterministic, so the anchors are identical.
    digest = hashlib.sha1(
        (os.path.abspath(path) + "\0" + content).encode("utf-8", "replace")
    ).hexdigest()[:8]
    return f"{os.path.basename(path)}:{digest}"


def _find_hits(r: SkimResult, query: str, cap: int) -> list[dict]:
    q = query.lower()
    hits: list[dict] = []
    for idx, line in enumerate(r._lines, start=1):
        if len(hits) >= cap:
            break
        if q in line.lower():
            covering = next((aid for aid, (s, e) in r.anchors.items() if s <= idx <= e), None)
            hits.append({
                "line": idx,
                "text": line.strip()[:200],
                "anchor": covering or "(already in skeleton)",
            })
    return hits


@mcp.tool()
def skim_open(path: str, query: str = "") -> dict:
    """Open a large file and return a compact skeleton + expandable anchor ids (not the full text).

    Returns handle, report (token counts + compression ratio), skeleton (read this), and anchors
    (ids you can expand). Use instead of reading a whole large file when you only need parts.
    Collapsed bodies are NOT in the skeleton - expand the anchor when the answer needs the body.
    Pass `query` to also get `matches` (which lines/anchors contain it) in the same call,
    saving a skim_search round-trip when you already know what you're looking for.
    """
    if not os.path.isfile(path):                       # missing OR a directory -> clean error, never a crash
        _log({"call": "skim_open", "path": path, "error": "not_a_file"})
        return {"error": f"not a readable file: {path}"}
    r = skim_file(path)
    handle = _handle_for(path, r.full_text)
    _remember(handle, r)

    skeleton = r.skeleton
    truncated = False
    if count_tokens(skeleton) > _SKELETON_TOKEN_SOFTCAP:
        kept, total = [], 0
        for line in skeleton.splitlines():
            total += count_tokens(line) + 1
            if total > _SKELETON_TOKEN_SOFTCAP and kept:
                break   # always keep at least the first line
            kept.append(line)
        skeleton = "\n".join(kept) + (
            f"\n# [skeleton truncated at ~{_SKELETON_TOKEN_SOFTCAP} tokens; "
            f"use skim_search(handle, query) to locate the spans you need]"
        )
        truncated = True

    report = r.report()
    result = {
        "handle": handle,
        "report": report,
        "skeleton_truncated": truncated,
        "skeleton": _STEER + "\n" + skeleton,   # anchor ids live in the skeleton's expand("aN") markers
        "anchor_count": len(r.anchors),         # no redundant id array; read ids from the skeleton
        "next": 'skim_expand(handle, anchors=["a1", ...]) to read exact spans',
    }
    if query:
        result["matches"] = _find_hits(r, query, 20)
    _log({
        "call": "skim_open", "handle": handle, "path": path, **({"query": query} if query else {}),
        "full_tokens": report["full_tokens"], "skeleton_tokens": report["skeleton_tokens"],
        "anchors": report["anchors"], "truncated": truncated,
        "result_tokens": count_tokens(json.dumps(result)),   # TRUE delivered size, not just skeleton
    })
    return result


_LINE_RANGE = re.compile(r"^L(\d+)-(\d+)$")


@mcp.tool()
def skim_expand(handle: str, anchors: list[str]) -> dict:
    """Return exact, verbatim source lines for one or more anchor ids from a skim_open result.

    Items can be anchor ids ("a7") or literal line ranges ("L120-180", 1-based inclusive) -
    ranges work even for lines shown in the skeleton, e.g. when a grep gave you line numbers.
    """
    r = _recall(handle)
    if r is None:
        _log({"call": "skim_expand", "handle": handle, "error": "unknown_handle"})
        return {"error": f"unknown handle {handle!r}; call skim_open first"}
    spans, missing = {}, []
    for aid in anchors:
        m = _LINE_RANGE.match(aid)
        if m:
            s, e = int(m.group(1)), int(m.group(2))
            if 1 <= s <= e <= len(r._lines):
                spans[aid] = "\n".join(r._lines[s - 1:e])
            else:
                spans[aid] = f"ERROR: range {aid!r} out of bounds (file has {len(r._lines)} lines)"
                missing.append(aid)
            continue
        try:
            spans[aid] = r.expand(aid)
        except KeyError:
            spans[aid] = f"ERROR: unknown anchor {aid!r}"
            missing.append(aid)
    result = {"handle": handle, "spans": spans}
    expand_tokens = sum(count_tokens(v) for a, v in spans.items() if a not in missing)
    _log({"call": "skim_expand", "handle": handle, "anchors": anchors,
          "found": [a for a in anchors if a not in missing], "missing": missing,
          "expand_tokens": expand_tokens, "result_tokens": count_tokens(json.dumps(result))})
    return result


@mcp.tool()
def skim_search(handle: str, query: str, max_results: int = 20) -> dict:
    """Find which anchors/lines contain `query` (case-insensitive) without reading the whole file."""
    r = _recall(handle)
    if r is None:
        _log({"call": "skim_search", "handle": handle, "error": "unknown_handle"})
        return {"error": f"unknown handle {handle!r}; call skim_open first"}
    hits = _find_hits(r, query, max(0, max_results))    # max_results <= 0 -> 0 hits (not 1)
    result = {"handle": handle, "query": query, "count": len(hits), "hits": hits}
    search_tokens = sum(count_tokens(h["text"]) for h in hits)
    _log({"call": "skim_search", "handle": handle, "query": query, "hits": len(hits),
          "search_tokens": search_tokens, "result_tokens": count_tokens(json.dumps(result))})
    return result


@mcp.tool()
def skim_run(command: str, timeout: int = 60) -> dict:
    """Run a shell command and return a COMPACT, expandable view of its output instead of the full dump.

    For verbose commands (test runs, builds, npm/pip, big logs): the skeleton shows the shape with
    critical lines (errors, codes, numbers) preserved and repeated blocks deduped; skim_expand(handle, ...)
    pulls exact output spans. Nothing is lost. Returns exit_code + a token report. Runs on your machine.
    """
    if os.environ.get("SKIM_RUN_DISABLED"):
        # opt-out for read-only mounts: the shell surface can be removed without losing the readers
        _log({"call": "skim_run", "command": command, "error": "disabled"})
        return {"error": "skim_run is disabled on this server (SKIM_RUN_DISABLED is set); "
                         "the read-only skim tools still work"}
    kwargs: dict = {"shell": True, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE}
    if os.name == "posix":
        kwargs["start_new_session"] = True     # own process group, so timeout can kill the whole tree
    try:
        proc = subprocess.Popen(command, **kwargs)
    except Exception as ex:
        _log({"call": "skim_run", "command": command, "error": repr(ex)})
        return {"error": f"failed to run: {ex!r}", "command": command}
    try:
        out_b, err_b = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)                       # timeout kills only the direct child (the shell); we
        try:                                   # take the grandchildren too, then reap
            proc.communicate(timeout=5)
        except Exception:
            pass
        _log({"call": "skim_run", "command": command, "error": "timeout"})
        return {"error": f"command timed out after {timeout}s (process tree killed)", "command": command}
    except Exception as ex:
        _log({"call": "skim_run", "command": command, "error": repr(ex)})
        return {"error": f"failed to run: {ex!r}", "command": command}

    # Decode as UTF-8 regardless of locale: dev tools (git, npm, pytest) emit UTF-8, and Windows'
    # default cp1252 would mojibake it. Bytes mode bypasses universal newlines, so normalize here.
    output = ((out_b or b"").decode("utf-8", "replace") + (err_b or b"").decode("utf-8", "replace"))
    output = output.replace("\r\n", "\n").replace("\r", "\n")
    r = skim_text(output, "log", path=f"$ {command}")
    handle = _handle_for(f"run::{command}", r.full_text)
    _remember(handle, r)

    skeleton = r.skeleton
    truncated = False
    if count_tokens(skeleton) > _SKELETON_TOKEN_SOFTCAP:
        kept, total = [], 0
        for line in skeleton.splitlines():
            total += count_tokens(line) + 1
            if total > _SKELETON_TOKEN_SOFTCAP and kept:
                break   # always keep at least the first line
            kept.append(line)
        skeleton = "\n".join(kept) + (
            f"\n# [skeleton truncated at ~{_SKELETON_TOKEN_SOFTCAP} tokens; "
            f"use skim_search(handle, query) / skim_expand to read specific output]"
        )
        truncated = True

    report = r.report()
    result = {
        "handle": handle,
        "exit_code": proc.returncode,
        "report": report,
        "skeleton_truncated": truncated,
        "skeleton": skeleton,
        "anchor_count": len(r.anchors),
        "next": 'skim_expand(handle, anchors=["a1", ...]) for exact output spans',
    }
    _log({
        "call": "skim_run", "command": command, "handle": handle, "exit_code": proc.returncode,
        "full_tokens": report["full_tokens"], "skeleton_tokens": report["skeleton_tokens"],
        "result_tokens": count_tokens(json.dumps(result)),
    })
    return result


_IMPORT_LINE = re.compile(r"^\s*(?:import|from|use|require|include|#include|using|package|source)\b(.*)$",
                          re.M)
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")


def _import_rank(candidates: list) -> dict:
    """PageRank over the file import graph: edge A->B when A's import lines mention B's stem.

    Language-agnostic on purpose (regex over import-ish lines, stem matching), dependency-free,
    and deterministic: edges are sorted, iteration order is fixed, ties break downstream by size
    then path. Reads only the first 64KB per file - imports live at the top.
    """
    stems: dict[str, list] = {}
    for fp in candidates:
        stems.setdefault(os.path.splitext(os.path.basename(fp))[0].lower(), []).append(fp)
    edges: dict = {}
    for fp in candidates:
        targets = set()
        try:
            with open(fp, "r", encoding="utf-8", errors="replace") as f:
                head = f.read(65_536)
            for m in _IMPORT_LINE.finditer(head):
                for tok in _IDENT.findall(m.group(1).lower()):
                    for other in stems.get(tok, ()):
                        if other != fp:
                            targets.add(other)
        except OSError:
            pass
        edges[fp] = sorted(targets)
    n = len(candidates)
    if n == 0:
        return {}
    d, rank = 0.85, {fp: 1.0 / n for fp in candidates}
    for _ in range(20):
        dangling = sum(rank[u] for u in candidates if not edges[u])
        base = (1 - d) / n + d * dangling / n
        new = {u: base for u in candidates}
        for u in candidates:
            out = edges[u]
            if out:
                share = d * rank[u] / len(out)
                for v in out:
                    new[v] += share
        rank = new
    return rank


_CODE_EXTS = {".py", ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".rb",
              ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".cs", ".php", ".kt", ".swift", ".scala"}
_IGNORE_DIRS = {".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__", ".pytest_cache",
                ".mypy_cache", ".ruff_cache", "dist", "build", ".idea", ".vscode", "target", ".tox",
                ".hypothesis", "htmlcov", ".next", ".cache", "vendor"}


@mcp.tool()
def skim_repo(path: str, query: str = "", budget_tokens: int = 6000, max_files: int = 400) -> dict:
    """Build a LOSSLESS, ranked, token-budgeted map of a whole repo/directory.

    Returns each code file's skeleton (signatures + structure, bodies folded), ranked by relevance to
    `query` (or by size if no query), trimmed to `budget_tokens`. Every file gets a handle, so
    skim_expand(handle, anchors=[...]) returns exact code from any file. Files that didn't fit are listed
    by name so you can skim_open them individually. Use to understand a codebase cheaply, then expand.
    """
    if not os.path.isdir(path):
        return {"error": f"not a directory: {path}"}

    # Walk the WHOLE tree so ranking sees every candidate (an early break would silently hide the
    # best match on big repos). The hard cap is a pathological-tree backstop and is surfaced, not silent.
    _SCAN_CAP = 20_000
    candidates, scan_truncated = [], False
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in _IGNORE_DIRS and not d.startswith(".")]
        for fn in files:
            if os.path.splitext(fn)[1].lower() in _CODE_EXTS:
                fp = os.path.join(root, fn)
                try:
                    sz = os.path.getsize(fp)
                except OSError:
                    continue
                if 0 < sz <= 2_000_000:
                    candidates.append(fp)
        if len(candidates) >= _SCAN_CAP:
            scan_truncated = True
            break

    def _size(fp):
        try:
            return os.path.getsize(fp)
        except OSError:
            return 0

    if query:
        def score(fp):
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as f:
                    return f.read(262_144).lower().count(query.lower())   # first 256KB is plenty for ranking
            except OSError:
                return 0
        candidates.sort(key=lambda fp: (-score(fp), -_size(fp), fp))
        ranking = "query"
    elif len(candidates) <= 1500:
        # No query: rank by import-graph centrality (PageRank) - the files everything else pulls
        # in are the ones worth reading first, not merely the biggest ones.
        rank = _import_rank(candidates)
        candidates.sort(key=lambda fp: (-round(rank.get(fp, 0.0), 12), -_size(fp), fp))
        ranking = "imports"
    else:
        candidates.sort(key=lambda fp: (-_size(fp), fp))   # too many files to read heads; size is free
        ranking = "size"
    candidates = candidates[:max_files]

    files_out, omitted, used, full_baseline = [], [], 0, 0
    for fp in candidates:
        rel = os.path.relpath(fp, path).replace("\\", "/")
        if used >= budget_tokens:
            omitted.append(rel)
            continue
        try:
            r = skim_file(fp)
        except Exception:
            continue
        sk = count_tokens(r.skeleton)
        if used + sk > budget_tokens and files_out:
            omitted.append(rel)
            continue
        handle = _handle_for(fp, r.full_text)
        _remember(handle, r)
        used += sk
        full_baseline += count_tokens(r.full_text)   # what reading these files in full would have cost
        files_out.append({"path": rel, "handle": handle, "lines": len(r._lines),
                          "anchors": len(r.anchors), "skeleton": r.skeleton})

    result = {
        "root": path,
        "query": query or None,
        "files_included": len(files_out),
        "code_files_found": len(candidates),
        "ranking": ranking,                 # query | imports (PageRank on the import graph) | size
        "scan_truncated": scan_truncated,   # True only if the 20k-file discovery backstop was hit
        "full_tokens": full_baseline,
        "used_tokens": used,
        "budget_tokens": budget_tokens,
        "files": files_out,
        "omitted": omitted[:60],
        "next": "skim_expand(<a file's handle>, anchors=[...]) for exact code, or skim_open an omitted file",
    }
    _log({"call": "skim_repo", "root": path, "query": query, "files_included": len(files_out),
          "code_files_found": len(candidates), "full_tokens": full_baseline, "used_tokens": used,
          "result_tokens": count_tokens(json.dumps(result))})
    return result


def _resolve_span(r: SkimResult, anchor: str):
    """(start, end) for an anchor id or literal "L<s>-<e>" range, else (None, reason)."""
    m = _LINE_RANGE.match(anchor)
    if m:
        s, e = int(m.group(1)), int(m.group(2))
        if not (1 <= s <= e <= len(r._lines)):
            return None, f"range {anchor!r} out of bounds (file has {len(r._lines)} lines)"
        return (s, e), None
    span = r.anchors.get(anchor)
    if span is None:
        return None, f"unknown anchor {anchor!r}"
    return span, None


@mcp.tool()
def skim_patch(handle: str, anchor: str, new_text: str) -> dict:
    """Replace exactly one anchored span (or literal "L<start>-<end>" range) of a skimmed file on disk.

    This is what verbatim-in-context buys: the span you expanded IS what the file contains, so an
    edit built from it applies safely. Expand the span first, edit that exact text, then patch.
    The write is refused if the file on disk no longer matches this handle's snapshot (drift ->
    clean error; re-open and rebuild the patch). Newline style (LF/CRLF) is preserved, the result
    is re-skimmed and verified, and a fresh handle for the new content is returned.
    Set SKIM_PATCH_DISABLED=1 to turn this tool off for read-only mounts.
    """
    if os.environ.get("SKIM_PATCH_DISABLED"):
        _log({"call": "skim_patch", "handle": handle, "error": "disabled"})
        return {"error": "skim_patch is disabled on this server (SKIM_PATCH_DISABLED is set); "
                         "the read-only skim tools still work"}
    r = _recall(handle)
    if r is None:
        _log({"call": "skim_patch", "handle": handle, "error": "unknown_handle"})
        return {"error": f"unknown handle {handle!r}; call skim_open first"}
    path = r.path
    if not os.path.isfile(path):
        _log({"call": "skim_patch", "handle": handle, "error": "not_a_file"})
        return {"error": f"handle {handle!r} does not reference a file on disk "
                         "(skim_run output cannot be patched)"}
    span, err = _resolve_span(r, anchor)
    if err:
        _log({"call": "skim_patch", "handle": handle, "anchor": anchor, "error": "bad_anchor"})
        return {"error": err}
    s, e = span
    try:
        with open(path, "rb") as f:
            raw = f.read()
        disk_text = raw.decode("utf-8")   # strict: refuse to rewrite bytes we cannot represent
    except UnicodeDecodeError:
        _log({"call": "skim_patch", "handle": handle, "error": "not_utf8"})
        return {"error": f"{path} is not valid UTF-8 on disk; refusing to patch"}
    except OSError as ex:
        _log({"call": "skim_patch", "handle": handle, "error": repr(ex)})
        return {"error": f"cannot read {path}: {ex}"}
    crlf = "\r\n" in disk_text
    if disk_text.replace("\r\n", "\n").replace("\r", "\n") != r.full_text:
        _log({"call": "skim_patch", "handle": handle, "error": "drift"})
        return {"error": f"{path} changed on disk since skim_open; call skim_open again and "
                         "rebuild the patch against the fresh handle"}
    new_lines = new_text.split("\n")
    merged = r._lines[:s - 1] + new_lines + r._lines[e:]
    out_text = "\n".join(merged)
    if crlf:
        out_text = out_text.replace("\n", "\r\n")
    try:
        with open(path, "wb") as f:                     # bytes: no platform newline translation
            f.write(out_text.encode("utf-8"))
    except OSError as ex:
        _log({"call": "skim_patch", "handle": handle, "error": repr(ex)})
        return {"error": f"cannot write {path}: {ex}"}
    r2 = skim_file(path)
    new_handle = _handle_for(path, r2.full_text)
    _remember(new_handle, r2)
    verified = r2.full_text == "\n".join(merged)        # re-read from disk matches the intent
    result = {
        "ok": verified,
        "path": path,
        "replaced": {"span": f"L{s}-{e}", "old_lines": e - s + 1, "new_lines": len(new_lines)},
        "newline_style": "crlf" if crlf else "lf",
        "verified": verified,
        "new_handle": new_handle,
        "report": r2.report(),
        "next": f"old handle still resolves against its snapshot; use {new_handle!r} for the new content",
    }
    _log({"call": "skim_patch", "handle": handle, "anchor": anchor, "new_handle": new_handle,
          "old_lines": e - s + 1, "new_lines": len(new_lines), "verified": verified,
          "result_tokens": count_tokens(json.dumps(result))})
    return result


@mcp.resource("skim://doc/{handle}/span/{anchor}")
def skim_span(handle: str, anchor: str) -> str:
    """Exact verbatim lines for one anchor id (or literal range "L<start>-<end>") of an open handle.

    Addressable in Claude Code as @skim:skim://doc/<handle>/span/<anchor> - a pull, not a tool
    round-trip. Same lossless contract as skim_expand.
    """
    r = _recall(handle)
    if r is None:
        return f"ERROR: unknown handle {handle!r}; call skim_open first"
    m = _LINE_RANGE.match(anchor)
    if m:
        s, e = int(m.group(1)), int(m.group(2))
        span = ("\n".join(r._lines[s - 1:e]) if 1 <= s <= e <= len(r._lines)
                else f"ERROR: range {anchor!r} out of bounds (file has {len(r._lines)} lines)")
    else:
        try:
            span = r.expand(anchor)
        except KeyError as ex:
            span = f"ERROR: {ex}"
    _log({"call": "skim_span_resource", "handle": handle, "anchor": anchor,
          "result_tokens": count_tokens(span)})
    return span


def main() -> None:
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "install":   # `skim-mcp install` = adoption, not serving
        from .install import main as install_main
        raise SystemExit(install_main(sys.argv[2:]))
    _log({"call": "_session_start", **_SESSION_META})   # one labeled line per launch = one session
    mcp.run()


if __name__ == "__main__":
    main()
