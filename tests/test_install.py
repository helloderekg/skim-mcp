"""install command: idempotent rule writes + registration command matches the install mode."""
import os

from skim.install import RULE_MARKER, build_add_command, ensure_rule, main, repo_root


def test_repo_root_detected_in_checkout():
    root = repo_root()
    assert root and os.path.isfile(os.path.join(root, "pyproject.toml"))


def test_add_command_uses_checkout_form_here():
    cmd = build_add_command()
    assert cmd[:5] == ["claude", "mcp", "add", "skim", "--"]
    assert "uv" in cmd and "--directory" in cmd and cmd[-1] == "skim-mcp"


def test_ensure_rule_writes_once(tmp_path):
    p = str(tmp_path / "CLAUDE.md")
    assert ensure_rule(p) is True
    once = open(p, encoding="utf-8").read()
    assert RULE_MARKER in once and "Prefer skim for large reads" in once
    assert ensure_rule(p) is False
    assert open(p, encoding="utf-8").read() == once     # byte-identical on the second run


def test_ensure_rule_appends_to_existing(tmp_path):
    p = str(tmp_path / "CLAUDE.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write("# my project\nexisting rules")          # note: no trailing newline
    assert ensure_rule(p) is True
    content = open(p, encoding="utf-8").read()
    assert content.startswith("# my project\nexisting rules\n")
    assert RULE_MARKER in content


def test_print_only_changes_nothing(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["--print-only"]) == 0
    out = capsys.readouterr().out
    assert "would run: claude mcp add skim" in out
    assert not (tmp_path / "CLAUDE.md").exists()
