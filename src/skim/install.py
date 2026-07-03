"""skim-mcp install - wire skim into Claude Code in one command.

Mounting an MCP server does not make a model USE it: the model's default for "read this file"
is the built-in Read tool, and server-level instructions pull weakly (especially on smaller
models). Adoption takes two steps: (1) register the server, (2) put a preference rule where the
model actually loads it every session - CLAUDE.md. This command does both, idempotently.

    skim-mcp install                       # register with Claude Code + project ./CLAUDE.md rule
    skim-mcp install --rule global         # write the rule to ~/.claude/CLAUDE.md instead
    skim-mcp install --rule none           # only register the server
    skim-mcp install --print-only          # show what would run / be written; change nothing
"""
from __future__ import annotations
import argparse
import os
import shutil
import subprocess

RULE_MARKER = "<!-- skim: prefer-skim-for-large-reads -->"
RULE_BLOCK = RULE_MARKER + """
## Prefer skim for large reads

When the skim MCP tools are available, prefer skim_open (files) and skim_repo (directories/repos)
over the built-in Read for anything larger than ~300 lines, and skim_run for verbose command
output (tests, builds, installs, big logs). Expand only the spans you need - skim is lossless,
so skimming first is never risky, only cheaper.
"""

_DESKTOP_SNIPPET = (
    '{"mcpServers": {"skim": {"command": "uvx", '
    '"args": ["--from", "skim-mcp[lang,tokens]", "skim-mcp"]}}}'
)


def repo_root() -> str | None:
    """The source-checkout root, if this module runs from one (same sniff as logpath)."""
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(os.path.dirname(here))
    return root if os.path.isfile(os.path.join(root, "pyproject.toml")) else None


def build_add_command() -> list:
    """The `claude mcp add` invocation matching how THIS copy of skim is installed."""
    root = repo_root()
    if root:
        return ["claude", "mcp", "add", "skim", "--",
                "uv", "run", "--directory", root.replace("\\", "/"), "skim-mcp"]
    exe = shutil.which("skim-mcp")
    if exe:
        return ["claude", "mcp", "add", "skim", "--", exe]
    return ["claude", "mcp", "add", "skim", "--",
            "uvx", "--from", "skim-mcp[lang,tokens]", "skim-mcp"]


def rule_path(target: str) -> str:
    if target == "global":
        return os.path.join(os.path.expanduser("~"), ".claude", "CLAUDE.md")
    return os.path.join(os.getcwd(), "CLAUDE.md")


def ensure_rule(md_path: str) -> bool:
    """Append the preference rule unless its marker is already present. True if written."""
    try:
        with open(md_path, encoding="utf-8") as f:
            existing = f.read()
    except OSError:
        existing = ""
    if RULE_MARKER in existing:
        return False
    parent = os.path.dirname(md_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(md_path, "a", encoding="utf-8") as f:
        if existing and not existing.endswith("\n"):
            f.write("\n")
        f.write("\n" + RULE_BLOCK)
    return True


def _run_add(cmd: list) -> bool:
    exe = shutil.which(cmd[0])
    if exe is None:
        return False
    attempt = [exe] + cmd[1:]
    try:
        return subprocess.run(attempt, timeout=60).returncode == 0
    except OSError:
        if os.name == "nt":   # .cmd shims: CreateProcess won't launch them bare, cmd.exe will
            try:
                return subprocess.run(["cmd", "/c", *attempt], timeout=60).returncode == 0
            except Exception:
                return False
        return False
    except Exception:
        return False


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="skim-mcp install",
        description="Register skim with Claude Code and write the CLAUDE.md preference rule "
                    "that makes Claude actually reach for it.",
    )
    ap.add_argument("--rule", choices=["project", "global", "none"], default="project",
                    help="where to write the prefer-skim rule (default: ./CLAUDE.md)")
    ap.add_argument("--print-only", action="store_true",
                    help="print what would run and be written; change nothing")
    args = ap.parse_args(argv)

    cmd = build_add_command()
    printable = " ".join(cmd)
    ok = True
    if args.print_only:
        print(f"would run: {printable}")
    elif _run_add(cmd):
        print("registered: skim is mounted in Claude Code (new sessions pick it up)")
    else:
        ok = False
        print("could not run the claude CLI automatically. Register manually:")
        print(f"  {printable}")
        print(f"or Claude Desktop (claude_desktop_config.json): {_DESKTOP_SNIPPET}")

    if args.rule != "none":
        path = rule_path(args.rule)
        if args.print_only:
            print(f"would write the prefer-skim rule to {path} (skipped when already present)")
        elif ensure_rule(path):
            print(f"rule written: {path} now tells Claude to prefer skim for large reads")
        else:
            print(f"rule already present in {path}; left unchanged")

    if not args.print_only:
        print("verify: tell a session to 'use skim to open a big file' and watch `skim-meter` tick")
    return 0 if ok else 1
