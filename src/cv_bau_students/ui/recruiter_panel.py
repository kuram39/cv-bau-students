"""Recruiter panel — one target job, two ranked candidate columns.

Reads everything from `candidates.repo` (interested candidates with a
Match row for the target ad). Left column = students-with-potential,
right column = experienced. Each row expands into a drill-in with the
score breakdown, bridge plan, translated capabilities, and the
role-specific Q&A the candidate submitted.
"""

from __future__ import annotations

import json

import streamlit as st

from cv_bau_students.candidates import repo as candidates_repo
from cv_bau_students.models import JobAd

TYPE_BADGE = {
    "student": "📚 Student",
    "career_changer": "🔄 Career-changer",
    "experienced": "💼 Experienced",
}


def render_recruiter_panel(target_ad: JobAd | None) -> None:
    if target_ad is None:
        st.warning(
            "Cílová pozice není v databázi. Spusť `python -m scripts.seed_target_demo` "
            "(po `ensure_seeded()`)."
        )
        return

    st.markdown(f"## 🧑‍💼 {target_ad.title}")
    st.caption(
        f"**{target_ad.employer or '—'}** · {target_ad.level} · "
        f"{target_ad.location} · {target_ad.remote_mode}"
    )

    stats = candidates_repo.stats_for_ad(target_ad.id)
    if stats["total"]:
        st.info(
            f"Pro tuto pozici je v DB **{stats['total']}** zájemců "
            f"(**{stats['students']}** student / **{stats['experienced']}** experienced). "
            f"Průměrné skóre — studenti: **{stats['avg_student_total']}**, "
            f"experienced: **{stats['avg_experienced_total']}**."
        )
    else:
        st.info(
            "Zatím žádní zájemci. Nahraj CV v záložce **Kandidát** a vyjádři zájem, "
            "nebo spusť seed skript pro předvyplnění demo dat."
        )

    left, right = st.columns(2, gap="large")
    with left:
        st.markdown("### 📚 Students-with-potential")
        st.caption("Vlastní scoring scale; osy stejné jako vpravo, kalibrace oddělená.")
        _render_column(target_ad.id, kind="student")
    with right:
        st.markdown("### 💼 Experienced kandidáti")
        st.caption("Stejná pipeline jako studenti — reálná porovnatelnost metrik.")
        _render_column(target_ad.id, kind="experienced")

    # Career-changers (if any) below, full width.
    changers = candidates_repo.get_candidates_for_ad(target_ad.id, kind="career_changer")
    if changers:
        st.markdown("### 🔄 Career-changers")
        for summary in changers:
            _render_candidate_row(target_ad.id, summary)

    # Collapsed job-description section at the bottom.
    with st.expander("📋 Popis pozice (rozbal pro detail inzerátu)"):
        st.markdown(f"**Must-have:** {', '.join(target_ad.must_have) or '—'}")
        st.markdown(f"**Nice-to-have:** {', '.join(target_ad.nice_to_have) or '—'}")
        langs = ", ".join(f"{lr.language} ({lr.min_level})" for lr in target_ad.languages_required)
        st.markdown(f"**Jazyky:** {langs or '—'}")
        st.markdown("**Text inzerátu:**")
        st.write(target_ad.raw_text)


def _render_column(ad_id: int, *, kind: str) -> None:
    summaries = candidates_repo.get_candidates_for_ad(ad_id, kind=kind)
    if not summaries:
        st.caption("_(zatím žádní zájemci v této kategorii)_")
        return
    for summary in summaries:
        _render_candidate_row(ad_id, summary)


def _render_candidate_row(ad_id: int, summary) -> None:
    badge = TYPE_BADGE.get(summary.kind, "❓")
    header = (
        f"{badge} · {summary.display_name} · "
        f"**{summary.total:.0f}** ± {summary.confidence_band:.0f}"
    )
    with st.container():
        st.markdown(header)
        st.progress(min(1.0, summary.total / 100))
        if summary.top_skills:
            st.caption("🏷 " + " · ".join(summary.top_skills))
        if summary.headline:
            st.caption(summary.headline)
        with st.expander("🔍 Detail kandidáta"):
            _render_detail(ad_id, summary.candidate_id)
        st.markdown("---")


def _render_detail(ad_id: int, candidate_id: int) -> None:
    detail = candidates_repo.get_candidate_detail(candidate_id, ad_id)
    if detail is None:
        st.caption("_(detail nedostupný)_")
        return

    m = detail.match
    c1, c2, c3 = st.columns(3)
    c1.metric("Skill fit", f"{m.skill_fit:.0f}")
    bridge_display = f"{m.bridge_fit:.0f}" if m.bridge_fit >= 0 else "N/A"
    c2.metric("Bridge fit", bridge_display)
    c3.metric("Personal fit", f"{m.personal_fit:.0f}")

    _render_skill_fit_detail(m.skill_fit_detail)

    if m.bridge_plan:
        st.markdown("**Bridge plan** (co doplnit pro vyšší úroveň):")
        for gap in m.bridge_plan:
            when = (
                f"~{gap.bridgeable_in_months} měs."
                if gap.bridgeable_in_months is not None
                else "🚫 jen praxí — bez zkratky"
            )
            st.caption(f"• {gap.skill} — {when}")

    if detail.role_answers:
        st.markdown("**Odpovědi na otázky k pozici:**")
        for a in detail.role_answers:
            if a.was_edited:
                tag = "✍️ upraveno"
            elif a.was_prefilled:
                tag = "🤖 AI návrh (přijato)"
            else:
                tag = "✍️ vlastní"
            st.markdown(f"_{a.question_text}_  \n{a.answer_text}  \n`{tag}`")

    if detail.capabilities:
        st.markdown("**Přeložené schopnosti:**")
        for cap in detail.capabilities[:8]:
            caveat = f" — _{cap.caveat}_" if cap.caveat else ""
            st.caption(
                f"• **{cap.skill}** ({cap.confidence:.0%}, {cap.source_type}): "
                f"„{cap.evidence_quote}“{caveat}"
            )

    if m.reasoning:
        st.markdown("**Zdůvodnění (AI):**")
        try:
            payload = json.loads(m.reasoning)
            st.write(payload.get("verdict", m.reasoning))
            for label, key, marker in (
                ("Silné stránky", "strengths", "+"),
                ("Mezery", "gaps", "−"),
                ("Otázky na pohovor", "interview_prompts", "❓"),
            ):
                items = payload.get(key, [])
                if items:
                    st.markdown(f"**{label}:**")
                    for item in items:
                        st.caption(f"{marker} {item}")
        except (json.JSONDecodeError, TypeError):
            st.write(m.reasoning)

    if detail.raw_cv_text:
        with st.expander("📄 Původní CV (raw text)"):
            st.text(detail.raw_cv_text)

    with st.expander("🔧 Raw profil JSON"):
        st.json(detail.profile.model_dump())


def _render_skill_fit_detail(d) -> None:
    """Why skill_fit is what it is: must/nice coverage + ESCO role match."""
    if d is None:
        return
    matched_must = ", ".join(d.matched_must) or "—"
    matched_nice = ", ".join(d.matched_nice) or "—"
    st.caption(f"✅ Must: {matched_must} · Nice: {matched_nice}")
    if d.missing_must:
        st.caption(f"❌ Chybí must: {', '.join(d.missing_must)}")

    if d.isco_code:
        label = d.occupation_label or "—"
        bonus = f" · bonus +{d.bonus_applied:.0f}" if d.bonus_applied else ""
        st.caption(
            f"🎯 Role: {label} (ISCO {d.isco_code}) — evidováno "
            f"{d.role_essential_evidenced}/{d.role_essential_total} "
            f"role-relevantních ESCO skills (essential+optional)"
            f"{bonus}"
        )
        if d.role_essential_matched:
            st.caption("🟢 Role-essential prokázané: " + " · ".join(d.role_essential_matched))
        if d.role_essential_missing:
            st.caption(
                "⚪ Role-essential chybějící (ukázka): " + " · ".join(d.role_essential_missing)
            )
