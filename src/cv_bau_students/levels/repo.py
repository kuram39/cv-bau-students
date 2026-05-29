"""Per-domain junior / medior / senior checklists + the bridge_plan query.

`bridge_plan` is the actionable side of the comparability stance: given
a target (domain, level) and the candidate's resolved skill ids, report
which skills the candidate is missing — split by "bridgeable in N
months" vs "experience-only, no shortcut". The matcher's bridge_fit
axis reads this list.
"""

from sqlalchemy import select

from cv_bau_students.db import get_session
from cv_bau_students.db_models import LevelChecklist, Skill
from cv_bau_students.models import GapItem


def bridge_plan(
    domain: str,
    level: str,
    candidate_skill_ids: set[int],
) -> list[GapItem]:
    """Return the GapItem list for the (domain, level) cell.

    Items already represented by the candidate are dropped. Each GapItem
    carries `bridgeable_in_months` (None when the gap is experience-only)
    and any free-text notes from the checklist.
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
