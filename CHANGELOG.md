# Changelog

All notable changes to skim are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow [SemVer](https://semver.org/).

## 0.1.1 - 2026-07-03

### Added

- Official MCP Registry metadata: `server.json` and the `mcp-name: io.github.helloderekg/skim-mcp`
  ownership marker in the README (the registry validates PyPI package ownership by finding that
  line in the published package's README).

## 0.1.0 - 2026-07-02

Initial public release.

### Added

- `skim_open(path)`: compact, lossless skeleton of a large file with expandable anchors.
  Python via `ast`; ~15 more languages (JS, TS, Go, Rust, Java, C, C++, Ruby, PHP, C#,
  Kotlin, Swift, Scala) via the optional tree-sitter `[lang]` extra; everything else through
  the generic block path.
- `skim_expand(handle, anchors)`: byte-exact retrieval of any folded span.
- `skim_search(handle, query)`: find which anchors hold a string without reading them.
- `skim_run(command)`: run a shell command, return a compact expandable view of its output.
  Disable entirely with `SKIM_RUN_DISABLED=1` for read-only mounts.
- `skim_repo(path, query)`: lossless, ranked, token-budgeted map of a whole directory tree.
- Retention layer: critical literals (error codes, dates, IPs, UUIDs, paths, versions,
  numbers, negations) are promoted into generic-path skeletons, never silently folded.
- Dedup: byte-identical blocks collapse to a pointer, still individually recoverable.
- `skim-meter`: live localhost dashboard of tokens in / out / saved, per session, with a
  Clear-to-ghost archive; `--once` text snapshot mode.
- Airtight invariant suite: lossless / round-trip-exact / bounds-valid / deterministic /
  never-crash, enforced by 150+ tests with Hypothesis fuzzing on every path.
- Call instrumentation to `skim_calls.jsonl` (local only) so the expand-loop is measurable.

- `skim_open(path, query=...)`: inline `matches` (line + covering anchor) with the open, saving a
  search round-trip. `skim_expand` accepts literal line ranges (`"L120-180"`) alongside anchor ids.
- Bounded LRU handle cache (default 512, `SKIM_MAX_HANDLES`); evicted/stale handles fail with a
  clean re-open error, never wrong data.
- `skim-meter --price-per-mtok` / `SKIM_PRICE_PER_MTOK`: opt-in dollars-saved display (no default
  price is shipped; prices go stale).
- Under-fetch eval harness: `eval/score_expand_loop.py` scores a session's log against
  `eval/QUESTIONS.md`, with the answers-are-hidden premise locked by a test.
- Binary files (git-style NUL sniff, first 8000 bytes) get an explicit not-byte-faithful note in
  the skeleton instead of silent replacement-char soup.
- Drain-style log templating (dependency-free): dense blocks show their top repeated shapes
  (`~412x GET /api/<*> took <*> ms`) in the skeleton; every line stays behind the anchor.
- `skim_repo` without a query ranks by import-graph centrality (dependency-free PageRank over
  which files import which) instead of raw size; result reports `ranking: query|imports|size`.
- Spans exposed as MCP resources: `skim://doc/{handle}/span/{anchor}`
  (`@skim:...` in Claude Code) - expansion as a pull, not a tool round-trip.
- Languages: Bash, Lua, and R join the tree-sitter set (~17 total; node kinds verified against
  real parses - Zig/Dart/Elixir probed and deferred, their bodies sit outside the function node).
- `skim_patch(handle, anchor, new_text)`: drift-safe span editing - refuses when the file changed
  on disk since `skim_open`, preserves LF/CRLF, re-verifies the write from disk, returns a fresh
  content-hashed handle (the old handle keeps reading its snapshot). Verbatim-in-context is what
  makes this safe; a transformed view cannot offer it. Disable with `SKIM_PATCH_DISABLED=1`.
- `skim-verify` console script: the five-invariant falsification checker as an installed command
  (multi-file, `--json`, CI-friendly exit codes); `check_invariant.py` remains as a thin wrapper
  around the same `skim.verify` module.
- `skim-mcp install`: one-command adoption - registers the server with Claude Code AND
  idempotently writes the prefer-skim rule to CLAUDE.md (`--rule project|global|none`,
  `--print-only`), with manual fallback output when the `claude` CLI isn't on PATH.
- Accuracy-vs-cost yardstick: `eval/accuracy_bench.py` regenerates `eval/ACCURACY.md` - per-question
  oracle pricing (full read vs skeleton + answer-bearing span, negatives shown) plus the live
  correctness protocol; other context tools are invited to score themselves under it.

### Fixed

- **Byte-exact reconstruction:** lines are split on real newlines only; form feeds, vertical tabs,
  NEL, and U+2028/U+2029 inside lines no longer shift `ast`/tree-sitter anchor alignment or break
  round-trips. Enforced by a new reconstruction invariant (`full_text` == decoded file).
- `skim_run` kills the whole process tree on timeout (`taskkill /F /T` on Windows,
  `start_new_session` + `killpg` on POSIX) instead of orphaning grandchildren.
- `skim_repo` walks the entire tree (20k-file backstop surfaced as `scan_truncated`) instead of
  silently stopping early, and ranks on the first 256KB per file.
- Skeleton truncation always keeps at least the first line.
- Eval scorer markers for Q3/Q4 named signature lines (visible in the skeleton, inside no anchor),
  so those questions could never score an expand hit; markers now point at body content and a
  premise test locks every scorer marker to >= 1 anchor and 0 skeleton leaks.

### Security

- Handles are content-hashed: re-opening a changed file or re-running a command with new
  output mints a new handle, so stale anchor ids can never silently resolve to different lines.
- `skim_run` decodes output as UTF-8 on every platform (Windows cp1252 mojibake fixed).
- Meter dashboard HTML-escapes all data-derived strings (paths, commands, session labels)
  and rejects non-loopback `Host` headers while bound to localhost (DNS-rebinding guard).
- CI dependency audit runs against the exported locked dependency set (previously it audited
  the audit tool's own environment).
