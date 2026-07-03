"""Guaranteed-retention layer - the differentiator.

Every surveyed compressor (LLMLingua = conditional perplexity, LLMLingua-2 = learned
keep/drop, Selective Context = self-information) is statistics-only and BLIND to the fact
that an identifier, a number, an error code, or a negation is load-bearing. For code, logs,
and structured data, dropping one of those corrupts the answer.

`critical_hits` finds the literals that must survive any compaction, so the skeleton can
PROMOTE them into view rather than hide them inside a collapsed span. This makes the
compression auditable: you can prove the critical set was surfaced.
"""
from __future__ import annotations
import re

# Ordered most-critical first. Each returns spans we never want silently dropped.
_PATTERNS = [
    re.compile(r"\b[A-Z]{2,}[-_]?\d{2,}\b"),                                   # error/status codes: E1042, ERR_001
    re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2})?\b"),            # dates / timestamps
    re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}(?::\d+)?\b"),                       # IPv4 (+optional port)
    re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"),  # UUID
    re.compile(r"(?:[A-Za-z]:\\|/)[\w./\\-]{2,}"),                            # file paths
    re.compile(r"\b0x[0-9a-fA-F]+\b"),                                         # hex
    re.compile(r"(?<![\w.-])\d+(?:\.\d+){1,}(?![\w.])"),                       # versions / dotted numbers: 1.2.3
    re.compile(r"(?<![\w.-])-?\d[\d,]*(?:\.\d+)?(?!\w)"),                      # plain numbers (allow trailing '.')
]

# Words that flip or signal meaning - negations and failure markers.
_CRIT_WORDS = re.compile(
    r"\b(?:not|no|never|none|null|nil|cannot|can't|without|fail(?:ed|ure)?|error|denied|"
    r"refused|invalid|missing|exception|fatal|timeout|timed?\s?out|panic|abort(?:ed)?|"
    r"unauthor\w*|forbidden|critical|warning)\b",
    re.I,
)


def critical_hits(text: str, cap: int = 10) -> list[str]:
    """Unique load-bearing literals in `text`, most-critical first, capped for readability.

    NOTE: the cap is a v0 display limit. The full guarantee (surface EVERY distinct critical
    literal, uncapped) is a config flag in the roadmap; here we cap to keep skeletons small.
    """
    seen: list[str] = []

    def add(s: str) -> None:
        s = s.strip().strip(",.;:()[]{}")  # drop punctuation picked up at span edges
        if s and s not in seen:
            seen.append(s)

    for pat in _PATTERNS:
        for m in pat.finditer(text):
            add(m.group(0))
        if len(seen) >= cap * 3:
            break
    for m in _CRIT_WORDS.finditer(text):
        add(m.group(0).lower())

    return seen[:cap]
