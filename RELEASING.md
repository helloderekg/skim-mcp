# Releasing skim

Releases publish to PyPI via GitHub's trusted publishing (OIDC) - no API tokens stored anywhere.

## One-time setup (already done for this repo)

1. On PyPI: project settings -> Publishing -> add a "trusted publisher" for
   `helloderekg/skim-mcp`, workflow `publish.yml`, environment `pypi`.
2. On GitHub: repo Settings -> Environments -> create `pypi` (optionally require a reviewer).

## Cutting a release

1. Update the version in `pyproject.toml` AND `src/skim/__init__.py` (`__version__`).
2. Add a dated section to `CHANGELOG.md`.
3. Run the gate locally; everything must be green:

   ```bash
   uv run pytest
   uv run python bench.py          # losslessness must stay at 100%
   uv build                        # sdist + wheel build cleanly
   ```

4. If the skeletonizer changed, regenerate the published numbers:

   ```bash
   uv run python benchmarks.py     # rewrites BENCHMARKS.md
   ```

   and update any figures quoted in `README.md`.
5. Commit, tag `vX.Y.Z`, push the tag, then create a GitHub release from it.
   Publishing the release triggers `.github/workflows/publish.yml`, which builds with
   `uv build` and uploads through trusted publishing.
6. Verify: `uvx skim-mcp@latest --help` resolves the new version, and the PyPI page renders
   the README.

## Versioning

- Patch: fixes that change no tool result shapes.
- Minor: new tools, new fields in results, new languages.
- Major: breaking changes to tool names, arguments, or result shapes (avoid; agents have
  long memories and old CLAUDE.md rules linger).
