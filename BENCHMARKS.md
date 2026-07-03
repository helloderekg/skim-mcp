# skim - benchmarks

Reproduce: `uv run python benchmarks.py` (regenerates this file). Measured on the running interpreter's standard library; token counts via tiktoken cl100k (proxy for Claude's tokenizer).

> Figures are measurements under these specific conditions (interpreter stdlib corpus, tiktoken cl100k counter, this machine/date) and are reproducible via this script - not guarantees under other conditions. Comparative figures (Aider/Basemind/Repomix) use their then-current public releases; corrections welcome via an issue.

## 1. Token savings on real code (whole-file skeleton)

Corpus: **60 real Python standard-library files**. Counter: tiktoken cl100k_base (proxy for Claude).

- **Overall: 387,911 tokens -> 122,660 (68.4% fewer, 3.16x).**
- Per-file ratio: min 1.5x, median 3.0x, mean 3.4x, max 11.3x.

| file | lines | full tokens | skeleton tokens | saved |
|---|---:|---:|---:|---:|
| `inspect.py` | 3,434 | 27,100 | 6,537 | 76% |
| `tarfile.py` | 3,032 | 25,180 | 7,645 | 70% |
| `_pydatetime.py` | 2,644 | 23,431 | 8,105 | 65% |
| `difflib.py` | 2,057 | 20,574 | 3,428 | 83% |
| `argparse.py` | 2,651 | 19,969 | 5,770 | 71% |
| `mailbox.py` | 2,154 | 16,637 | 7,712 | 54% |
| `pdb.py` | 1,988 | 15,429 | 4,731 | 69% |
| `dataclasses.py` | 1,589 | 14,592 | 3,602 | 75% |
| `statistics.py` | 1,455 | 13,832 | 3,244 | 77% |
| `threading.py` | 1,709 | 13,091 | 5,362 | 59% |

## 2. 1:1 before/after on a real task (distribution-level)

Task: *"read and understand the single largest function in this module"* - the model opens the file, reads the skeleton, and expands exactly the one function it needs. **Same answer, measured token cost, across 24 large modules** (this counts the full skim cost: skeleton + the expand).

| file | lines | function read | full read (tokens) | skim: skeleton+expand | saved |
|---|---:|---|---:|---:|---:|
| `tarfile.py` | 3,032 | `_proc_pax` (119 lines) | 25,180 | 8,906 | **65%** |
| `_pydatetime.py` | 2,644 | `_wrap_strftime` (63 lines) | 23,431 | 8,582 | **63%** |
| `locale.py` | 1,780 | `currency` (45 lines) | 21,848 | 2,055 | **91%** |
| `optparse.py` | 1,682 | `parse_args` (37 lines) | 12,830 | 5,610 | **56%** |
| `pathlib.py` | 1,436 | `walk` (43 lines) | 11,242 | 5,421 | **52%** |
| `nntplib.py` | 1,094 | `_getlongresp` (44 lines) | 9,443 | 3,526 | **63%** |
| `uuid.py` | 794 | `main` (46 lines) | 7,698 | 3,069 | **60%** |
| `codecs.py` | 1,130 | `iterencode` (16 lines) | 7,660 | 4,161 | **46%** |
| `bdb.py` | 921 | `effective` (48 lines) | 7,279 | 3,243 | **55%** |
| `socketserver.py` | 864 | `serve_forever` (27 lines) | 5,824 | 3,615 | **38%** |
| `mimetypes.py` | 657 | `_default_mime_types` (199 lines) | 5,756 | 3,194 | **45%** |
| `webbrowser.py` | 690 | `register_standard_browsers` (77 lines) | 5,280 | 2,467 | **53%** |
| **24-file total** | | | **176,897** | **71,877** | **59%** |

Per-task savings: min 30%, median 51%, mean 51%, max 91% (across 24 tasks).

## 3. Head-to-head vs existing approaches (same 30 files)

| approach | tokens | % of full | lossless? |
|---|---:|---:|:--:|
| full read (Claude `Read`) | 184,277 | 100% | yes |
| **skim skeleton** | **64,043** | **34.8%** | **yes (lazy-expand)** |
| signatures-only (Aider/Basemind mechanism) | 20,276 | 11.0% | no (bodies gone) |

Repomix `--compress` measured separately at **57.5% of full, lossy** (needs `npx`; see `COMPARISON.md`). skim is the only lossless option, and beats Repomix on tokens.

## 4. Runtime & scaling

| input | lines | time | per 1k lines |
|---|---:|---:|---:|
| Python source | 1,750 | 5.8 ms | 3.34 ms |
| Python source | 8,750 | 33.2 ms | 3.79 ms |
| Python source | 35,000 | 177.3 ms | 5.07 ms |
| log (generic path) | 100,000 | 41 ms | 0.41 ms |

Scaling is ~linear; peak Python heap on a ~30k-line file: **105 MB**. Pure CPU, no GPU, no network, no model calls.

## 5. Correctness (airtight)

- **Lossless: 0 of 54,215 non-blank lines unrecoverable across 80 files (100.00% recoverable).** Every line is shown or one `expand` away.
- Both code and generic paths guarantee losslessness *by construction* (coverage-completion sweep).
- Test suite: 202 tests, ~80% coverage, incl. Hypothesis property fuzzing of both paths.
- Adversarial campaign: ~18,000 fuzz cases; the Python path survived 12,000 with 0 failures; every bug found is fixed and regression-locked.

