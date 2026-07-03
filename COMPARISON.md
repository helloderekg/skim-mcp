# skim vs existing tools — measured head-to-head

Reproduce: `uv run python compare.py <corpus_dir> 30`, then
`npx -y repomix <corpus_dir> --compress --style plain --output <out>`, then
`uv run python compare.py --count <out>`.

Corpus: 30 real Python stdlib files. Token counts via tiktoken `cl100k_base` (same counter for all).

| Approach | Tokens | % of full | Lossless? | Notes |
|---|---:|---:|:--:|---|
| Full read (Claude `Read`) | 184,277 | 100% | yes | the baseline an agent pays today |
| **skim skeleton** | **64,043** | **34.8%** | **yes** | signatures + docstring-1st-line + bodies/comments as expandable anchors |
| Repomix `--compress` | 105,963 | 57.5% | no | signatures + **full docstrings**, bodies dropped; ~1.5% scaffolding |
| Signatures-only (Aider/Basemind repo-map mechanism) | 20,276 | 11.0% | no | signatures only; docstrings/bodies/comments gone |

## Findings

- **vs Repomix `--compress`: skim is a measured improvement** — 40% fewer tokens (64k vs 106k) AND lossless vs Repomix's lossy. Repomix is larger because it preserves entire multi-line docstrings inline.
- **vs Aider/Basemind repo-maps: a tradeoff, not a loss** — they compress ~3× harder but irreversibly discard bodies, docstrings, and comments. skim keeps everything recoverable at ~3× their tokens.
- **vs Claude native `Grep` + `Read(offset/limit)`: marginal** — that's already lossless + targeted; skim's edge is map-first convenience.
- **skim is the only lossless option of the three compressors.** That is its real, defensible niche: the lossless middle. An agent that must edit code can't trust a lossy repo-map; it would re-read the full file. skim lets it pull exact spans.

## Caveats

- **Basemind (pure Rust) was NOT installed** — no `cargo` on this machine. The 11% figure is a faithful reproduction of the signatures-only mechanism via `ast`, not the Basemind binary.
- **Language breadth still favors Basemind**: skim ships Python (`ast`) + ~17 verified tree-sitter languages; Basemind claims 300+. skim adds grammars only after verifying each language's folding against real parses; anything unwired falls back to the (lossless) generic path.
- Corpus is Python stdlib; results will shift by language and codebase style.
