"""Research/MTF divergence classification (Phase 6 Objective 5).

DIAGNOSTIC ONLY -- these classifications evaluate whether the experimental
research layer is providing information beyond the existing MTF score.
They are never trading signals and never feed back into either score.
"""

ALIGNED_STRONG = "ALIGNED_STRONG"
ALIGNED_WEAK = "ALIGNED_WEAK"
RESEARCH_UPGRADE = "RESEARCH_UPGRADE"
RESEARCH_DOWNGRADE = "RESEARCH_DOWNGRADE"
MAJOR_DIVERGENCE = "MAJOR_DIVERGENCE"
INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

# A "major" divergence overrides a plain upgrade/downgrade classification --
# tuned to flag cases at least as large as the Phase 5 RELIANCE finding
# (research 37.85 vs mtf 31.92, ~+6 points but a 3-rank jump) without being
# so wide it never fires. EXPERIMENTAL threshold, not backtested.
MAJOR_SCORE_GAP = 25.0
MAJOR_RANK_GAP = 3
UPGRADE_SCORE_GAP = 10.0
UPGRADE_RANK_GAP = 2
STRONG_SCORE_THRESHOLD = 60.0
WEAK_SCORE_THRESHOLD = 40.0


def classify_divergence(
    mtf_score: float,
    mtf_rank: int | None,
    research_score: float | None,
    research_rank: int | None,
) -> tuple[float | None, int | None, str]:
    """Returns (research_minus_mtf, research_rank_minus_mtf_rank, classification).
    A negative rank delta means research ranked the candidate BETTER
    (lower rank number = higher rank) than MTF did."""
    if research_score is None:
        return None, None, INSUFFICIENT_DATA

    score_delta = round(research_score - mtf_score, 2)
    rank_delta = (research_rank - mtf_rank) if (research_rank is not None and mtf_rank is not None) else None

    if abs(score_delta) >= MAJOR_SCORE_GAP or (rank_delta is not None and abs(rank_delta) >= MAJOR_RANK_GAP):
        return score_delta, rank_delta, MAJOR_DIVERGENCE

    if score_delta >= UPGRADE_SCORE_GAP or (rank_delta is not None and rank_delta <= -UPGRADE_RANK_GAP):
        return score_delta, rank_delta, RESEARCH_UPGRADE

    if score_delta <= -UPGRADE_SCORE_GAP or (rank_delta is not None and rank_delta >= UPGRADE_RANK_GAP):
        return score_delta, rank_delta, RESEARCH_DOWNGRADE

    average_level = (mtf_score + research_score) / 2
    classification = ALIGNED_STRONG if average_level >= STRONG_SCORE_THRESHOLD else ALIGNED_WEAK
    if WEAK_SCORE_THRESHOLD <= average_level < STRONG_SCORE_THRESHOLD:
        # Genuinely mid-range and aligned -- neither "strong" nor "weak" is
        # accurate; default to ALIGNED_WEAK (the more conservative label)
        # rather than inventing a third bucket the spec didn't ask for.
        classification = ALIGNED_WEAK

    return score_delta, rank_delta, classification
