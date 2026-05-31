"""Streamlit dual-panel demo — Kandidát + Recruiter in one app.

Two tabs:
  - 👤 Kandidát — upload CV, answer minimal BAU questions if needed,
    see matched roles, express interest, fill role-specific questions.
  - 🧑‍💼 Recruiter — one target job, two ranked candidate columns
    (students vs experienced) with drill-in detail.

Single `streamlit run`; the tabs share the same SQLite, so a CV
uploaded in the Kandidát tab appears in the Recruiter tab after the
candidate expresses interest.

Run via:
    streamlit run src/cv_bau_students/ui/app.py
"""

from __future__ import annotations

import os

import streamlit as st
from dotenv import load_dotenv

from cv_bau_students.bootstrap import ensure_seeded, prewarm_llm
from cv_bau_students.jobads.repo import find_ad_by_title_substring
from cv_bau_students.ui.candidate_panel import render_candidate_panel
from cv_bau_students.ui.recruiter_panel import render_recruiter_panel

load_dotenv()

# Streamlit Cloud delivers secrets via st.secrets; bridge to env so
# llm.call_json (which reads os.environ) works in both deploy modes.
if not os.environ.get("ANTHROPIC_API_KEY"):
    try:
        os.environ["ANTHROPIC_API_KEY"] = st.secrets["ANTHROPIC_API_KEY"]
    except (KeyError, FileNotFoundError):
        pass

# The demo's single target role. The seed script prepares this ad.
TARGET_TITLE = "Datový analytik"

st.set_page_config(page_title="cv-bau-students", page_icon="🧑‍💼", layout="wide")
st.title("cv-bau-students — matching studentů a absolventů")
st.caption(
    "Demo: jedna cílová pozice, kandidáti nahrávají CV (záložka Kandidát), "
    "recruiter vidí obodované zájemce (záložka Recruiter)."
)

if not os.environ.get("ANTHROPIC_API_KEY"):
    st.error("Chybí `ANTHROPIC_API_KEY`. Lokálně: `.env`. Cloud: Streamlit Secrets.")
    st.stop()

ensure_seeded()
prewarm_llm()

target_ad = find_ad_by_title_substring(TARGET_TITLE)

tab_candidate, tab_recruiter = st.tabs(
    ["👤 Kandidát (nahraj CV)", "🧑‍💼 Recruiter (obodovaní zájemci)"]
)

with tab_candidate:
    render_candidate_panel(target_ad)

with tab_recruiter:
    render_recruiter_panel(target_ad)


# --- ESCO attribution footer (CC BY 4.0 requirement) ---------------------
st.markdown(
    "---\n"
    "*This service uses the ESCO classification of the European Commission.* "
    "ESCO v1.2.x · [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) · "
    "Czech NSP/CDK (CC0, [data.mpsv.cz](https://data.mpsv.cz))."
)
