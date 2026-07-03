# skim expand-loop validation — the gate

This eval measures the one risk that can sink skim: **does the model actually call `skim_expand`
when the answer lives in a collapsed span, or does it answer from the skeleton and get it wrong
(under-fetch)?** Every answer below is in a function *body* or a collapsed log block — never in the
skeleton — so a correct answer requires an expand.

## How to run

1. Mount skim (`claude mcp add skim -- uv run --directory /abs/path/to/skim-mcp skim-mcp`) and restart.
2. In a fresh session, for each question: tell Claude to use `skim` and ask it, pointing at the
   fixture (`eval/widget.py` / `eval/run.log`). Do **not** hint that it should expand — that's the
   behavior we're measuring.
3. Score mechanically: `uv run python eval/score_expand_loop.py` reads the call log (repo root
   `skim_calls.jsonl` for a source checkout, `~/.skim/` for installed copies), derives the
   answer-key anchors from the fixtures by content, and prints the per-session
   expand-when-needed rate against the pass bar below.

The premise (every answer hidden from the skeleton, recoverable by expand) is locked by
`tests/test_eval_premise.py` — if a skeletonizer or retention change ever surfaces an answer,
the suite fails before the eval silently degrades.

## Questions

### widget.py (answer is in a function body, not the signature)
1. What discount rate does the **gold** tier get? — expect `0.18` (anchor: `compute_discount` body)
2. What prefix must a valid API token start with, and how long must it be? — expect `sk_live_`, `32` chars
3. How long does the **3rd** retry (attempt index 2) wait? — expect `9` seconds
4. Under what condition is shipping free? — expect country `US` **and** weight ≤ `5` kg
5. What label does status code **418** map to? — expect `teapot`

### run.log (answer is in a collapsed / deduped block)
6. What exit code did the service give up with, and after how many retries? — expect exit `70`, after `3`
7. Which host was unreachable? — expect `10.0.0.9:5432`

## Scoring (from skim_calls.jsonl + Claude's answers)

| Metric | How | Pass bar (directional) |
|---|---|---|
| **Expand-when-needed rate** | fraction of Qs where a `skim_expand` on the right anchor preceded the answer | ≥ 80% |
| **Confident-wrong-without-expand** | fraction where Claude answered (wrongly) with no expand | < 10% |
| **Over-expand** | expanded far more anchors than needed (defeats the savings) | watch, not a hard fail |

If under-fetch is high, the fix is steering (already added: the `# skim:` header + self-advertising
anchors) tuned up, or a **hybrid push** (auto-expand the top relevance-ranked anchor, like Aider) —
test both in this same harness before building the log engine.
