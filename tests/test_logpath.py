"""Server and meter must agree on one log location in every install mode."""
import os

from skim.logpath import default_log_path


def test_env_var_wins(monkeypatch):
    monkeypatch.setenv("SKIM_LOG_FILE", "/tmp/custom.jsonl")
    assert default_log_path() == "/tmp/custom.jsonl"


def test_source_checkout_uses_repo_root(monkeypatch):
    # this test suite runs from the checkout, so the repo-root branch is the live one
    monkeypatch.delenv("SKIM_LOG_FILE", raising=False)
    p = default_log_path()
    root = os.path.dirname(p)
    assert os.path.basename(p) == "skim_calls.jsonl"
    assert os.path.isfile(os.path.join(root, "pyproject.toml"))


def test_meter_and_server_agree(monkeypatch):
    monkeypatch.delenv("SKIM_LOG_FILE", raising=False)
    from skim.meter import _default_log
    assert _default_log() == default_log_path()
