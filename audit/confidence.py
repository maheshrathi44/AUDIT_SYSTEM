"""
Confidence scoring — how much a rule's automated result should be trusted.

Built from a running confirm/disagree tally per rule, not a flat point score:
    score = (confirm + PRIOR_WEIGHT) / (confirm + disagree + 2 * PRIOR_WEIGHT)

This is a Beta-Bernoulli posterior mean with a symmetric neutral prior — a rule
with no votes yet sits exactly at the Medium midpoint. PRIOR_WEIGHT controls how
many real votes it takes to move off that midpoint: with PRIOR_WEIGHT = 2, two
ticks in a row (no disagreements between them) cross from Medium into High, and
two crosses/unticks in a row cross from Medium into Low.

Standalone module — does not import from or get called by any existing
extraction/filtering/traversal/verdict/report code. Nothing here changes how a
verdict itself is computed; it only scores a tally that's attached afterward.
"""

from __future__ import annotations

PRIOR_WEIGHT = 2  # "worth" of the neutral starting position, in votes

# A rule extracted from a Past Audit Report starts with this much built-in trust —
# equivalent to PRIOR_WEIGHT real confirmations, which lands exactly at High.
REPORT_SOURCE_SEED_CONFIRM  = PRIOR_WEIGHT
REPORT_SOURCE_SEED_DISAGREE = 0


def seed_tally(is_manual: bool) -> tuple[int, int]:
    """Starting (confirm, disagree) counts for a rule with no saved history yet."""
    if is_manual:
        return REPORT_SOURCE_SEED_CONFIRM, REPORT_SOURCE_SEED_DISAGREE
    return 0, 0


def confidence_score(confirm: int, disagree: int) -> float:
    """0.0-1.0 trust score from the confirm/disagree tally."""
    return (confirm + PRIOR_WEIGHT) / (confirm + disagree + 2 * PRIOR_WEIGHT)


def confidence_label(confirm: int, disagree: int) -> str:
    """
    Low / Medium / High. Uses integer comparisons equivalent to splitting the
    0-1 score into equal thirds, so there's no floating-point boundary error —
    a boundary value is credited to the outer band (High or Low) on both sides,
    keeping the up/down behavior symmetric.
    """
    if confirm >= 2 * disagree + PRIOR_WEIGHT:
        return "High"
    if disagree >= 2 * confirm + PRIOR_WEIGHT:
        return "Low"
    return "Medium"
