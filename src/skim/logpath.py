"""One shared answer to "where is skim_calls.jsonl?" for the server and the meter.

Priority: SKIM_LOG_FILE env var; else the repo root when running from a source checkout
(the historical behavior, keeps the log next to the code you're hacking on); else a stable
user-level path (~/.skim/) so a PyPI/uvx install and its meter agree on one location even
though they may live in different ephemeral environments.
"""
from __future__ import annotations
import os


def default_log_path() -> str:
    env = os.environ.get("SKIM_LOG_FILE")
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))     # .../src/skim  or  .../site-packages/skim
    root = os.path.dirname(os.path.dirname(here))         # repo root, if this is a checkout
    if os.path.isfile(os.path.join(root, "pyproject.toml")):
        return os.path.join(root, "skim_calls.jsonl")
    return os.path.join(os.path.expanduser("~"), ".skim", "skim_calls.jsonl")
