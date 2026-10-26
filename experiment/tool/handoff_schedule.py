"""Explicit handoff-interval lists. This module does not import Mini-NDN."""

from __future__ import annotations

import math
from typing import List, Optional


def parse_explicit_intervals(text: str, handoff_count: int) -> List[float]:
    """Return K+1 non-negative durations: K pre-handoff waits, then the tail.

    Empty fields are rejected so a trailing comma cannot shorten the list.
    """
    if handoff_count < 0:
        raise ValueError(f"handoff count must be non-negative: {handoff_count}")
    tokens = [part.strip() for part in text.split(",")]
    expected = handoff_count + 1
    if len(tokens) != expected or any(token == "" for token in tokens):
        raise ValueError(
            f"NLSR_HANDOFF_INTERVALS has {len([token for token in tokens if token])} "
            f"value(s); {handoff_count} handoffs require {expected}, including the tail"
        )
    values: List[float] = []
    for token in tokens:
        try:
            value = float(token)
        except ValueError as exc:
            raise ValueError(f"Invalid NLSR_HANDOFF_INTERVALS value: {token}") from exc
        if not math.isfinite(value) or value < 0:
            raise ValueError(f"NLSR_HANDOFF_INTERVALS values must be non-negative: {token}")
        values.append(value)
    return values


def intervals_from_env(raw: Optional[str], handoff_count: int) -> Optional[List[float]]:
    """None when the variable is unset or blank. Otherwise a validated list."""
    if raw is None or not str(raw).strip():
        return None
    return parse_explicit_intervals(str(raw).strip(), handoff_count)


def format_intervals(values: List[float]) -> str:
    """Stable params.txt representation. Three decimal places matches the schedule file."""
    return ",".join(f"{value:.3f}" for value in values)
