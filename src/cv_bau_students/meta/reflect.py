"""Phase 8.5 — privacy-filtered LLM reflection over recent pipeline runs.

Reads the most recent `matches` rows + their parent profile-versions,
extracts only aggregate metadata (no CV text, no candidate names, no
ad URLs), feeds the meta_reflect prompt, appends the response to the
repo-root `IMPROVEMENT_LOG.md`.

Cost: one LLM call per reflection batch (~$0.01).
"""

from __future__ import annotations

import json
import statistics
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from cv_bau_students import llm
from cv_bau_students.config import PROMPTS_DIR
from cv_bau_students.db import get_session
from cv_bau_students.db_models import (
    Candidate,
    Match,
    ProfileVersion,
    TranslatedCapabilityRow,
)

LOG_FILE = Path("IMPROVEMENT_LOG.md")


def reflect(*, batch_size: int = 20, log_path: Path | None = None) -> dict:
    """Produce a reflection JSON + append a dated entry to IMPROVEMENT_LOG.md.

    Returns the parsed payload so callers (tests, CLI) can read it back
    without re-parsing the log file.
    """
    metadata = _collect_metadata(batch_size)
    if metadata["analyses_seen"] == 0:
        return {"observations": [], "suggested_adjustments": [], "open_questions": []}

    prompt = llm.render_prompt(
        "meta_reflect",
        batch_size=metadata["analyses_seen"],
        metadata_json=json.dumps(metadata, ensure_ascii=False),
        prompt_files=", ".join(sorted(p.name for p in PROMPTS_DIR.glob("*.md"))),
    )
    payload = llm.call_json(prompt)

    _append_log(payload, metadata, log_path or LOG_FILE)
    return payload


def _collect_metadata(batch_size: int) -> dict:
    """Walk the DB for the last N analyses; emit privacy-safe aggregates."""
    with get_session() as session:
        latest_candidates = (
            session.execute(
                select(Candidate).order_by(Candidate.created_at.desc()).limit(batch_size)
            )
            .scalars()
            .all()
        )
        per_type: dict[str, int] = {}
        per_round_count: list[int] = []
        confidence_samples: list[float] = []
        below_threshold = 0
        for candidate in latest_candidates:
            per_type[candidate.type] = per_type.get(candidate.type, 0) + 1
            rounds = (
                session.execute(
                    select(ProfileVersion).where(ProfileVersion.candidate_id == candidate.id)
                )
                .scalars()
                .all()
            )
            per_round_count.append(max(0, len(rounds) - 1))
            caps = (
                session.execute(
                    select(TranslatedCapabilityRow).where(
                        TranslatedCapabilityRow.candidate_id == candidate.id
                    )
                )
                .scalars()
                .all()
            )
            for cap in caps:
                confidence_samples.append(cap.confidence)
                if cap.confidence < 0.4:
                    below_threshold += 1

        matches = (
            session.execute(select(Match).order_by(Match.created_at.desc()).limit(batch_size * 5))
            .scalars()
            .all()
        )
    return {
        "analyses_seen": len(latest_candidates),
        "candidate_type_distribution": per_type,
        "completion_round_counts": per_round_count,
        "avg_translator_confidence": (
            round(statistics.mean(confidence_samples), 3) if confidence_samples else None
        ),
        "below_confidence_floor_count": below_threshold,
        "match_score_distribution": _score_distribution(matches),
        "match_axis_spread": _axis_spread(matches),
    }


def _score_distribution(matches: list[Match]) -> dict[str, float | None]:
    if not matches:
        return {"min": None, "p50": None, "max": None}
    totals = sorted(m.total for m in matches)
    return {
        "min": round(min(totals), 1),
        "p50": round(totals[len(totals) // 2], 1),
        "max": round(max(totals), 1),
    }


def _axis_spread(matches: list[Match]) -> dict[str, float | None]:
    if not matches:
        return {"skill_fit_avg": None, "bridge_fit_avg": None, "personal_fit_avg": None}
    return {
        "skill_fit_avg": round(statistics.mean(m.skill_fit for m in matches), 1),
        "bridge_fit_avg": round(statistics.mean(m.bridge_fit for m in matches), 1),
        "personal_fit_avg": round(statistics.mean(m.personal_fit for m in matches), 1),
    }


def _append_log(payload: dict, metadata: dict, log_path: Path) -> None:
    timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    block = [
        f"## {timestamp} — reflection on batch of {metadata['analyses_seen']} analyses",
        "",
        "### Observations",
    ]
    block.extend(f"- {obs}" for obs in payload.get("observations", []))
    block.append("")
    block.append("### Suggested adjustments")
    for item in payload.get("suggested_adjustments", []):
        block.append(
            f"- `{item.get('rubric_or_prompt')}` → {item.get('change')} "
            f"(rationale: {item.get('rationale')})"
        )
    block.append("")
    block.append("### Open questions")
    block.extend(f"- {q}" for q in payload.get("open_questions", []))
    block.append("")
    block.append("---")
    block.append("")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write("\n".join(block))
