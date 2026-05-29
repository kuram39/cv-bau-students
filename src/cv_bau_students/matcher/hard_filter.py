"""Hard KO filter — applied before scoring.

Rules:
- Language requirement: candidate must reach the ad's min CEFR level
  for each `languages_required` entry. Missing language → fail.
- Remote-mode preference: not enforced yet (no candidate-side
  preference field). Placeholder for the recruiter UI.
- Location: not enforced for the prototype.
"""

from cv_bau_students.models import CandidateProfile, JobAd

CEFR_RANK = {"A1": 1, "A2": 2, "B1": 3, "B2": 4, "C1": 5, "C2": 6}


def passes_hard_filter(profile: CandidateProfile, ad: JobAd) -> bool:
    """Return True when the candidate is eligible to be scored against the ad."""
    candidate_levels = {
        lang.language.strip().lower(): CEFR_RANK.get(lang.min_level.strip().upper(), 0)
        for lang in profile.languages
    }
    for required in ad.languages_required:
        required_rank = CEFR_RANK.get(required.min_level.strip().upper(), 0)
        if required_rank == 0:
            continue  # ad didn't specify a CEFR level → treat as soft
        candidate_rank = candidate_levels.get(required.language.strip().lower(), 0)
        if candidate_rank < required_rank:
            return False
    return True
