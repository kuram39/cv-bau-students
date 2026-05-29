"""Rank a candidate against the full ad corpus.

Combines hard_filter + score_match for every ad in the DB. Returns the
top-N ranked MatchScore list ready to feed reasoning + UI.
"""

from cv_bau_students.jobads.repo import list_ads
from cv_bau_students.matcher.hard_filter import passes_hard_filter
from cv_bau_students.matcher.score import score_match
from cv_bau_students.models import CandidateProfile, MatchScore, TranslatedCapability


def rank_candidate(
    profile: CandidateProfile,
    capabilities: list[TranslatedCapability],
    *,
    top_n: int = 10,
) -> list[MatchScore]:
    """Run the matcher across every ad and return the top-N by total score."""
    ads = list_ads()
    scored: list[MatchScore] = []
    for ad in ads:
        if not passes_hard_filter(profile, ad):
            continue
        scored.append(score_match(profile, capabilities, ad))
    scored.sort(key=lambda m: m.total, reverse=True)
    return scored[:top_n]
