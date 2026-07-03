## What this changes

<!-- One or two sentences. Link the issue if there is one. -->

## Checklist

- [ ] `uv run pytest` passes (invariants are non-negotiable: lossless, round-trip exact,
      in-bounds, deterministic, never-crash)
- [ ] New behavior has a test; a bug fix has a regression test
- [ ] If the skeletonizer changed: `uv run python bench.py` still reports 100% lossless,
      and I checked the compression ratio didn't quietly collapse
- [ ] Core stays stdlib-only (`tokens` and `server` may use optional deps)
- [ ] Tool output stays ASCII (no em-dashes or fancy glyphs; they break Windows consoles)
