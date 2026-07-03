"""Token + size accounting.

Exact char counts are always available. Token estimates use tiktoken's cl100k_base
when installed - a close PROXY for Claude's tokenizer, not identical. Treat the numbers
as relative measures of savings, not exact Claude billing counts.
"""
from __future__ import annotations

try:
    import tiktoken  # type: ignore

    _enc = tiktoken.get_encoding("cl100k_base")
    _EXACT = True

    def count_tokens(text: str) -> int:
        return len(_enc.encode(text))

except Exception:  # tiktoken not installed -> heuristic
    _EXACT = False

    def count_tokens(text: str) -> int:
        # ~4 chars/token is a reasonable proxy for code + English
        return max(1, round(len(text) / 4))


def token_basis() -> str:
    return "tiktoken cl100k_base (proxy for Claude)" if _EXACT else "heuristic ~4 chars/token (proxy)"
