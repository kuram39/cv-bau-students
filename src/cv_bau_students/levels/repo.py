"""Per-domain junior / medior / senior checklists + the bridge_plan query.

`bridge_plan` is the actionable side of the comparability stance: given
a target (domain, level) and the candidate's resolved skill ids, report
which skills the candidate is missing — split by "bridgeable in N
months" vs "experience-only, no shortcut". The matcher's bridge_fit
axis reads this list.
"""

from functools import lru_cache

from sqlalchemy import select

from cv_bau_students.db import get_session
from cv_bau_students.db_models import LevelChecklist, Skill
from cv_bau_students.models import GapItem


@lru_cache(maxsize=128)
def checklist_exists(domain: str, level: str) -> bool:
    """True when at least one row exists for (domain, level).

    Used by the matcher to distinguish two semantically different empty
    bridge_plan results:

    - Empty AND checklist exists → candidate meets every expected skill.
    - Empty AND checklist missing → we have no rubric to score against.

    The second case must NOT produce a "100" bridge_fit (false ready
    signal); the matcher emits a `None` sentinel instead.
    """
    with get_session() as session:
        row = session.execute(
            select(LevelChecklist.id)
            .where(LevelChecklist.domain == domain, LevelChecklist.level == level)
            .limit(1)
        ).first()
    return row is not None


def bridge_plan(
    domain: str,
    level: str,
    candidate_skill_ids: set[int],
) -> list[GapItem]:
    """Return the GapItem list for the (domain, level) cell.

    Items already represented by the candidate are dropped. Each GapItem
    carries `bridgeable_in_months` (None when the gap is experience-only)
    and any free-text notes from the checklist.

    Note: an empty return list is ambiguous on its own. Callers wanting
    to score against the absence of a checklist should also consult
    `checklist_exists(domain, level)`.
    """
    with get_session() as session:
        rows = session.execute(
            select(LevelChecklist, Skill)
            .join(Skill, Skill.id == LevelChecklist.skill_id)
            .where(LevelChecklist.domain == domain, LevelChecklist.level == level)
        ).all()
        gaps: list[GapItem] = []
        for checklist_row, skill in rows:
            if skill.id in candidate_skill_ids:
                continue
            gaps.append(
                GapItem(
                    skill=skill.canonical_name,
                    bridgeable_in_months=checklist_row.bridgeable_in_months,
                    notes=checklist_row.notes,
                )
            )
        return gaps
