"""skim - token-efficient skim-then-expand I/O for agentic models."""
from .skeleton import skim_file, skim_text, SkimResult
from .tokens import count_tokens, token_basis
from .retain import critical_hits

__all__ = ["skim_file", "skim_text", "SkimResult", "count_tokens", "token_basis", "critical_hits"]
__version__ = "0.1.0"
