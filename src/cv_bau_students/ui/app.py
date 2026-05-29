"""Streamlit recruiter view.

Two ranked lists side-by-side (per owner spec): students-with-potential
on the left, mocked experienced candidates on the right. Each entry has
a candidate-type badge, confidence band, evidence panel, bridge plan,
and recommended interview prompts.

Run via:
    streamlit run src/cv_bau_students/ui/app.py
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import streamlit as st
from dotenv import load_dotenv

from cv_bau_students.db import init_db
from cv_bau_students.jobads.repo import list_ads
from cv_bau_students.models import CandidateAnalysis, JobAd, MatchScore
from cv_bau_students.pipeline import analyze_candidate

load_dotenv()

# Streamlit Cloud delivers secrets via st.secrets; bridge to env so
# llm.call_json (which reads os.environ) works in both deploy modes.
if not os.environ.get("ANTHROPIC_API_KEY"):
    try:
        os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
    except (KeyError, FileNotFoundError):
        pass


def _find_ad_by_id(ad_id: int) -> JobAd | None:
    for ad in list_ads():
        if ad.id == ad_id:
            return ad
    return None


def _render_student_match(match: MatchScore) -> None:
    """Render one student-match card."""
    ad_meta = _find_ad_by_id(match.ad_id)
    title = f"#{match.ad_id} — {ad_meta.title if ad_meta else 'Ad'}"
    with st.container():
        st.markdown(f"**📚 Student** · {title}")
        st.progress(min(1.0, match.total / 100))
        st.caption(
            f"Total {match.total} ± {match.confidence_band} | "
            f"skill {match.skill_fit} | bridge {match.bridge_fit} | "
            f"personal {match.personal_fit}"
        )
        if match.bridge_plan:
            st.markdown("**Bridge plan**:")
            for gap in match.bridge_plan:
                bridgeable = (
                    f" — ~{gap.bridgeable_in_months} mo"
                    if gap.bridgeable_in_months is not None
                    else " — experience-only, no shortcut"
                )
                st.caption(f"• {gap.skill}{bridgeable}")
        if match.reasoning:
            try:
                payload = json.loads(match.reasoning)
            except json.JSONDecodeError:
                payload = {"verdict": match.reasoning}
            st.markdown(f"_Verdict:_ {payload.get('verdict', '')}")
            for label, key, marker in (
                ("Strengths", "strengths", "+"),
                ("Gaps", "gaps", "−"),
                ("Interview prompts", "interview_prompts", "❓"),
            ):
                items = payload.get(key, [])
                if not items:
                    continue
                st.markdown(f"**{label}**")
                for item in items:
                    st.caption(f"{marker} {item}")
        st.markdown("---")


st.set_page_config(page_title="cv-bau-students recruiter view", page_icon="📚", layout="wide")
st.title("📚 cv-bau-students — recruiter view")
st.caption("Studentský / changer pipeline — odděleně ranked vůči BAU experienced output.")

if not os.environ.get("ANTHROPIC_API_KEY"):
    st.error("Chybí `ANTHROPIC_API_KEY`. Lokálně: `.env`. Cloud: Streamlit Secrets.")
    st.stop()

init_db()

TYPE_BADGE = {
    "student": "📚 Student",
    "career_changer": "🔄 Career-changer",
    "experienced": "💼 Experienced",
}


@dataclass
class MockExperiencedCandidate:
    name: str
    role: str
    score: int
    summary: str


_MOCK_EXPERIENCED = [
    MockExperiencedCandidate(
        name="Lucie K.",
        role="Senior Data Analyst",
        score=82,
        summary="7 yrs analytics at Avast + Seznam. Owns full pipeline + stakeholder mgmt.",
    ),
    MockExperiencedCandidate(
        name="Marek P.",
        role="Backend Engineer",
        score=78,
        summary="5 yrs Python + Postgres in fintech. Looking for product-shaped backend role.",
    ),
    MockExperiencedCandidate(
        name="Eva D.",
        role="UX Designer",
        score=74,
        summary="6 yrs product design in SaaS. Strong portfolio in B2B onboarding flows.",
    ),
]


uploaded = st.file_uploader("Nahraj CV studenta (PDF / DOCX)", type=["pdf", "docx"])
if not uploaded:
    st.info("👆 Vyber CV pro analýzu.")
    st.stop()

if st.button("🚀 Spustit matching", type="primary"):
    with st.spinner("Analyzuji CV (5-6 LLM volání)…"):
        try:
            result = analyze_candidate(uploaded.getvalue(), uploaded.name)
        except Exception as exc:  # noqa: BLE001 — surface to user
            st.error(f"Pipeline error: {exc}")
            st.stop()
    st.session_state["last_analysis"] = result.model_dump()

analysis_dict = st.session_state.get("last_analysis")
if not analysis_dict:
    st.info("Klikni na **Spustit matching** pro vyhodnocení nahraného CV.")
    st.stop()

analysis = CandidateAnalysis.model_validate(analysis_dict)

# --- Top header ------------------------------------------------------------

st.subheader(
    f"{TYPE_BADGE.get(analysis.profile.candidate_type, '❓')} "
    f"· {analysis.profile.candidate_type} · "
    f"language {analysis.profile.language.upper()}"
)
if analysis.processing_metadata.get("detector_reasons"):
    st.caption("Detector reasons: " + " | ".join(analysis.processing_metadata["detector_reasons"]))

if analysis.missing_fields:
    st.warning(
        "⚠️ Profil obsahuje chybějící data: "
        + ", ".join(analysis.missing_fields)
        + ". V produkčním flow by tu byl candidate-facing completion krok."
    )


# --- Two ranked lists -----------------------------------------------------

left, right = st.columns(2, gap="large")


with left:
    st.markdown("### 📚 Students-with-potential")
    st.caption("Vlastní scoring scale; nepřímo porovnatelný s pravým sloupcem.")
    if not analysis.matches:
        st.info(
            "Žádné inzeráty neprošly hard filtrem. "
            "Spusť `scripts/generate_synthetic_ads.py` nebo "
            "drop scraped JSON do `data/raw_ads/scraped/`."
        )
    else:
        for match in analysis.matches:
            _render_student_match(match)


with right:
    st.markdown("### 💼 Experienced candidates (BAU output — mock)")
    st.caption("Mock BAU output. V produkci přichází z BAU pipeline.")
    for cand in _MOCK_EXPERIENCED:
        with st.container():
            st.markdown(f"**{TYPE_BADGE['experienced']}** {cand.name} — {cand.role}")
            st.progress(cand.score / 100)
            st.caption(cand.summary)
            st.markdown("---")


with st.expander("🔧 Raw analysis JSON"):
    st.json(analysis.model_dump())
