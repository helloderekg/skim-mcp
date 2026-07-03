---
name: Bug report
about: Something skimmed wrong, crashed, or broke an invariant
labels: bug
---

## What happened

<!-- What did you run, what did you expect, what did you get instead? -->

## The invariant check

If the bug is about skimming a specific file (wrong skeleton, missing lines, bad anchors),
please run the invariant checker against it and paste the output:

```bash
uv run python check_invariant.py path/to/the/file
```

If the file is private, any snippet that reproduces the issue works - the suite's regression
tests are built from exactly these.

## Environment

- OS:
- Python version:
- skim version (`pip show skim-mcp` or the repo commit):
- Extras installed (`[lang]`? `[tokens]`?):
- MCP client (Claude Code / Claude Desktop / other + version):

## Log line (optional)

If relevant, the matching line(s) from `skim_calls.jsonl` (paths only, no file contents are
logged - redact anything you'd rather not share).
