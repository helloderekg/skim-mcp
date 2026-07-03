# Contributing to skim

Thanks for helping make skim better. It's small, dependency-light, and held to a hard correctness bar.

## Setup

```bash
uv sync --extra dev          # installs the MCP SDK + pytest/hypothesis/tiktoken
uv run pytest                # run the suite
uv run python bench.py       # invariant sweep + compression numbers over the stdlib
uv run skim-verify <files>   # check files against the invariants (multi-file, --json, exit codes)
uv run python check_invariant.py <file>   # same checker, single-file JSON form
```

## The invariants (non-negotiable)

Every change must preserve these for **any** readable input — they are enforced by the test suite
(`tests/test_invariants.py`, property-based via Hypothesis) and by `check_invariant.py`:

1. **Lossless** — every non-blank original line is shown verbatim in the skeleton OR recoverable through an anchor.
2. **Round-trip exact** — `expand(anchor)` returns the original bytes for that range, unchanged.
3. **Reconstruction exact** — `full_text` equals the decoded file content byte-for-byte (lines are
   split on real newlines only; `\f`, `\v`, NEL, U+2028/U+2029 are content, never line breaks).
4. **Bounds valid** — every anchor range is `1 <= start <= end <= n_lines`.
5. **Deterministic** — skimming the same input twice yields a byte-identical skeleton.
6. **No crash** — `skim_file` never raises on a readable file (unparseable code falls back to the generic path).

If you change the skeletonizer, run `uv run python bench.py` and confirm losslessness stays at 100%.

## Adding a language

The engine (anchors, coverage sweep, expand, dedup, retention, report) is language-agnostic — it works
on line ranges. A new language needs a front-end that yields `(definition_line_range, body_line_range)`
tuples; see `DESIGN.md` for the tree-sitter plan.

## Style

- Standard library only in the core (`tokens` and `server` may use optional deps). Keep it that way.
- Match the surrounding code. ASCII in tool output (no em-dashes / fancy glyphs — they break on Windows consoles).
- New behavior gets a test. New edge case found in the wild gets a regression test in `tests/test_regressions.py`.
