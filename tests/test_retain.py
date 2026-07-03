"""Retention layer: critical literals are detected and punctuation-trimmed."""
from skim import critical_hits


def test_finds_codes_ips_numbers():
    h = critical_hits("ERR502 at 10.0.0.9 port 5432 on 2026-06-27, exit 70")
    assert "ERR502" in h
    assert "10.0.0.9" in h
    assert "5432" in h
    assert "2026-06-27" in h


def test_strips_trailing_punctuation():
    h = critical_hits("count 20, total 10342.")
    assert "20" in h and "10342" in h
    assert "20," not in h and "10342." not in h


def test_finds_negations_and_failure_words():
    h = [w.lower() for w in critical_hits("the token is not valid and never refreshed; request failed")]
    assert any(w in ("not", "never", "failed", "invalid") for w in h)


def test_cap_respected():
    many = " ".join(f"AB{i:04d}" for i in range(50))   # 50 distinct error-code-shaped hits
    hits = critical_hits(many, cap=10)
    assert len(hits) <= 10
