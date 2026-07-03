# Skim — token-efficient I/O for agentic models

**Audience: a model like Claude (Claude Code / desktop Claude on Windows), mid-session, paying for every token it reads.** Not academic researchers.

## The problem

An agentic session burns most of its tokens on three things:

1. **Large file reads** — a 2,000-line file is ~20k tokens, and I usually need 40 of those lines.
2. **Verbose tool output** — test runs, build logs, `npm`/`pip` output, big JSON.
3. **Repeated reads** — re-reading a file I already half-saw, re-running a command.

A closed model (Claude via API) **cannot ingest latent vectors** — the academic latent-compression methods (gist tokens, ICAE, 500xCompressor) need model weights we don't have. So the only levers available to a model like me are **text-level** and **I/O architecture**. That is exactly the layer an MCP tool lives in.

## The core idea: skim-then-expand (lazy, *not* lossy)

Instead of reading the whole thing, the model calls `skim(path)` and gets back a **skeleton**:

- the structure — symbols, signatures, headings, section starts
- each collapsed region replaced by an **anchor** (`a1`, `a2`, …) and a line count
- everything verbatim that it *does* keep (no paraphrasing of signatures, identifiers, numbers)

The model reads the skeleton cheaply, decides what it actually needs, and calls `expand("a7")` to pull *only those spans* — at full, byte-exact fidelity.

**The distinction that makes this work:** summarization is *lossy and irreversible* (you can't get the original back). Skim is *lazy* — nothing is destroyed, expansion is always one call away. That is what lets a closed model safely operate on a compressed view: it can always drill down, so it never loses information, only defers reading it.

This is the original "read it compressed, decompress only what you need" intuition — realized at the tool layer, where a closed model can actually use it.

## How it plugs into a model like me

Ships as an **MCP server**. Claude Code / desktop Claude connects over stdio:

```
claude mcp add skim -- uvx skim-mcp            # once published
claude mcp add skim -- uv run --directory C:/CascadeProjectsTop/skim skim-mcp   # local dev
```

Then I call `skim` / `expand` the way I call `Read` / `Bash` today — but tool results come back small, with a handle to pull detail on demand. Tool results count against my context like any text, so the win is direct: a smaller result *is* a cheaper turn.

## Architecture

| Module | Job |
|---|---|
| `skeleton` | code → structural skeleton (Python `ast`; ~15 languages via tree-sitter); logs/text → generic block outline. Collapsed regions become anchors. |
| `retain` | the generic path **never** drops identifiers, numbers, dates, error codes, or negations — they're promoted into the skeleton. The code path gets this free by keeping signatures verbatim. |
| `tokens` | count tokens (exact char counts always; `tiktoken` estimate when present) so savings are measured, not claimed, and budgets are enforceable. |
| `server` | the MCP surface; per-session `handle → SkimResult` with `anchor → exact span (line range)`, so `expand` is byte-exact and lossless. |
| dedup (in `skeleton`) | content-hash blocks; a repeated block collapses to a pointer (`identical to a3`) instead of re-dumping. |

## MCP surface (verified contract)

Tool results count against my context exactly like text — Claude Code warns above **10k tokens** and hard-caps at **25k** (override per-tool via `_meta["anthropic/maxResultSizeChars"]`, ≤500k chars). So the rule is **skeleton inline, detail by reference**, and `skim_open` keeps the skeleton under the 10k warning line.

- `skim_open(path)` → `{handle, report, skeleton, anchor_count, next}` — the skeleton (anchor ids live in its `expand("aN")` markers) is the only thing that normally lands in context.
- `skim_expand(handle, anchors[])` → exact verbatim spans for just those anchors.
- `skim_search(handle, query)` → which anchors/lines contain a string, without reading them.
- `skim_run(command)` → run a shell command, return a compact, expandable view of its output (tests / builds / logs).
- `skim_repo(path, query)` → a lossless, ranked, token-budgeted map of a whole repo; expand exact code from any file.
- `skim_patch(handle, anchor, new_text)` → drift-safe span editing: because expands are verbatim, an edit built
  from one applies safely — refused when the file changed since `skim_open`. The demo of WHY verbatim matters;
  a transformed-view compressor cannot offer it.
- *Shipped:* spans as MCP **resources** via the `skim://doc/{handle}/span/{anchor}` template, addressable in Claude Code as `@skim:skim://doc/<handle>/span/<anchor>` — expansion as a pull, not a tool round-trip.

Register (Windows): `claude mcp add skim -- uv run --directory C:/CascadeProjectsTop/skim skim-mcp`

## What's novel here (verified against 2026 prior art)

Code skeletonization is **table-stakes, not novel.** Aider's repo-map (static, tree-sitter + NetworkX PageRank over a symbol-reference graph) and **Basemind** (an MCP server that already does code outline→expand: "pull back only the one function it needs, nothing is lost") both ship it. Repomix, codebase-memory-mcp, and Code-Context-Engine cover adjacent ground. We include code skeletonization because it's useful, not because it's ours.

The genuinely unfilled combination — confirmed absent across all of the above and across Claude's own (content-agnostic, lossy) context-editing:

1. **Generality beyond code.** Every prior tool is structurally tied to a parseable symbol/reference graph, so it degrades or doesn't apply to logs, JSON/NDJSON, CSV, transcripts, API dumps. skim's generic path treats those as first-class — the open lane.
2. **A hard retention guarantee.** No surveyed tool *promises* that specific identifiers, numbers, error codes, or negations survive compaction — all are relevance/signature-gated, so a load-bearing literal in a "low-rank" span silently vanishes. skim promotes critical literals into the skeleton (auditable).
3. **Dedup of repeated spans** keyed to stable anchors, with span-level (not file-level) lazy expand.

Closest competitor: **Basemind** (code-only, no documented retention/dedup guarantee). Differentiate on generality + retention + dedup — *not* on the expand idea itself, which is already proven (atlassian-labs/mcp-compressor applies the same skim-then-expand pattern to MCP tool catalogs). Position skim as **complementary** to Claude's native context-editing: a smarter, recoverable, content-aware read, not a replacement for tool-result clearing.

## Status & build sequence (decided 2026-06-27, research-backed)

**Done:** v0 core (Python `ast` skeleton + generic retention/dedup). Benchmarked on an 80-file stdlib corpus (tiktoken, `bench.py`): **2.95× overall / ~3.0× median, 66% saved, 100% lossless, deterministic, ~7 ms/file**. The first benchmark caught a real losslessness bug — 9% of lines (standalone comments + module-docstring tails that `ast` omits) were unrecoverable; fixed with a coverage-completion sweep → now 100% recoverable, at a ~17% ratio cost (3.6× → 3.0× median). The earlier "5.3× on argparse" was a cherry-picked single-file, pre-fix number; honest headline is ~3× median.

**Also shipped since:** multi-language code skeletons via tree-sitter (~15 languages — JS/TS/Go/Rust/Java/C/C++/Ruby/PHP/C#/Kotlin/Swift/Scala; JS measured at 6.6× / 85% lossless); `skim_run(command)` (lossless command/test/build-output compression through the generic path); `skim_repo(path, query)` (ranked, token-budgeted, lossless whole-repo map with per-file expand). Six MCP tools total (`skim_open` / `skim_expand` / `skim_search` / `skim_run` / `skim_repo` / `skim_patch`), with call instrumentation + a steering header, plus `skim-verify` (user-runnable falsification of the lossless contract) and `skim-mcp install` (server registration + the CLAUDE.md preference rule in one idempotent command — mounting alone doesn't create usage). 202 tests, ~80% coverage, Hypothesis fuzzing of both paths, an ~18,000-case adversarial campaign (every bug fixed and regression-locked), and a clean dependency audit.

**Next, in order:**

1. **Validate the expand-loop live — the gate.** The thesis depends on the model reliably calling `expand` when an answer needs a hidden span. Evidence is two-sided: on-demand fetch is Anthropic's own pattern and the Tool Search Tool *improves* accuracy (Opus 4.5 79.5%→88.1%), but under-fetch is real (models answer from insufficient context 30–40% of the time), and a skeleton "looks complete," which can worsen it. Cheap mitigations added (steering header + self-advertising anchors); the harness is now mechanized — `eval/score_expand_loop.py` scores any session's `skim_calls.jsonl` against `eval/QUESTIONS.md`, the answers-hidden premise (and every scorer marker) is locked by `tests/test_eval_premise.py`, and `eval/accuracy_bench.py` regenerates `eval/ACCURACY.md`, the accuracy-vs-cost yardstick other tools can be scored on. If under-fetch is high, add a hybrid push (auto-expand the top relevance-ranked anchor, like Aider).
2. ~~Drain log templating~~ **Shipped** as a dependency-free Drain-style templater (`templater.py`): dense blocks (>40 lines) show their top repeated shapes (`~412x GET /api/<*> ...`) in the skeleton; all lines stay behind the block anchor, so the lossless contract is untouched.
3. ~~PageRank ranking / more languages / resources~~ **Shipped:** `skim_repo` ranks by import-graph PageRank when no query is given (dependency-free power iteration; edges from import-ish lines to file stems); Bash/Lua/R joined the tree-sitter set (node kinds verified against real parses; Zig/Dart/Elixir were probed and skipped — their body nodes sit outside the function node); spans are MCP resources. **Remaining:** structured-data skeleton (TOON/TSV reformat + schema/value-stats, ~2–5× ceiling), the tree-sitter long tail, hybrid push (auto-expand top anchor) if the eval shows high under-fetch, and publishing for `uvx skim-mcp`.
