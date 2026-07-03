"""Drain-style log templating - the dense-log lane.

A big repetitive block (service logs, test spam, retry storms) compresses poorly as "N more
lines": the model can't see WHAT repeats. This clusters lines into templates the way Drain does
(fixed token count + positional similarity, varying tokens wildcarded to <*>), so the skeleton
can show "~412x  GET /api/<*> took <*> ms" instead of hiding a thousand near-identical lines.

Deterministic by construction: clusters form in input order, merging is positional, and the
output sort breaks count ties by first occurrence. Pure stdlib; the anchors still cover every
original line, so this is a VIEW on top of the lossless contract, never a replacement for it.
"""
from __future__ import annotations

_SIMILARITY = 0.5      # Drain's classic default: >= half the tokens match positionally
_MAX_SHOW = 6          # skeleton budget: top templates only; the rest is one summary line


def log_templates(lines: list, max_show: int = _MAX_SHOW, min_count: int = 3):
    """Cluster `lines` into (count, template, first_line_index) triples, biggest clusters first.

    Returns (shown_templates, total_template_count). Lines are grouped by token count, then
    merged into the first existing template with >= _SIMILARITY positional matches; mismatched
    positions become <*>. Only templates with >= min_count members are worth skeleton space.
    """
    groups: dict[int, list] = {}            # token_count -> [ [tokens, count, first_idx], ... ]
    for idx, ln in enumerate(lines):
        toks = ln.split()
        n = len(toks)
        if n == 0:
            continue
        best = None
        for tpl in groups.get(n, []):
            same = sum(1 for a, b in zip(tpl[0], toks) if a == b or a == "<*>")
            if same / n >= _SIMILARITY:
                best = tpl
                break                        # first match wins -> deterministic
        if best is None:
            groups.setdefault(n, []).append([list(toks), 1, idx])
        else:
            best[0] = [a if a == b else "<*>" for a, b in zip(best[0], toks)]
            best[1] += 1
    repeated = [t for lst in groups.values() for t in lst if t[1] >= min_count]
    repeated.sort(key=lambda t: (-t[1], t[2]))
    shown = [(t[1], " ".join(t[0]), t[2]) for t in repeated[:max_show]]
    return shown, len(repeated)
