"""Candidate panel — the BAU-mirroring multi-step upload journey.

State machine via `st.session_state["cand_step"]`:

  upload      → file uploader + run button
  completion  → BAU-mandatory questions (only if generic pass needs them)
  matches     → top-N match preview cards, each with interest buttons
  role_form   → role-specific questions pre-filled from the CV
  done        → confirmation card

All heavy work (LLM calls) happens inside spinners; results are stashed
in session_state so Streamlit's per-interaction reruns don't recompute.
"""

from __future__ import annotations

import streamlit as st

from cv_bau_students.models import GenericResult, InterestResult
from cv_bau_students.pipeline import (
    express_interest,
    run_generic_pass,
    submit_role_specific,
)

TYPE_BADGE = {
    "student": "📚 Student",
    "career_changer": "🔄 Career-changer",
    "experienced": "💼 Experienced",
}


def render_candidate_panel() -> None:
    step = st.session_state.get("cand_step", "upload")
    if step == "upload":
        _step_upload()
    elif step == "matches":
        _step_matches()
    elif step == "role_form":
        _step_role_form()
    elif step == "done":
        _step_done()
    else:
        _step_upload()


def _reset() -> None:
    for k in (
        "cand_step",
        "generic_result",
        "selected_ad_id",
        "interest_result",
        "final_result",
    ):
        st.session_state.pop(k, None)


def _step_upload() -> None:
    st.markdown("### 👤 Nahraj své CV")
    st.caption(
        "Systém z CV vytáhne povinné údaje (jméno, lokalita, vzdělání, "
        "zkušenosti, hard + soft skills, jazyky) a najde vhodné pozice. "
        "Skóre vidí pouze recruiter."
    )
    uploaded = st.file_uploader("CV (PDF / DOCX / TXT / MD)", type=["pdf", "docx", "txt", "md"])
    if uploaded and st.button("🚀 Najít pozice", type="primary"):
        with st.spinner("Zpracovávám CV (~4 LLM volání, ~30 s)…"):
            try:
                result = run_generic_pass(uploaded.getvalue(), uploaded.name)
            except Exception as exc:  # noqa: BLE001
                st.error(f"Chyba pipeline: {exc}")
                return
        st.session_state["generic_result"] = result.model_dump()
        if result.status == "needs_completion":
            st.session_state["cand_step"] = "upload"  # stay; show the warning below
            st.warning(
                "CV neobsahuje všechny povinné údaje pro matching: "
                + _format_missing(result)
                + ". V plném produktu by tu byl krátký doplňovací formulář; "
                "pro demo prosím nahraj kompletnější CV."
            )
        else:
            st.session_state["cand_step"] = "matches"
            st.rerun()


def _format_missing(result: GenericResult) -> str:
    if result.completion_round and result.completion_round.questions:
        return ", ".join(q.field for q in result.completion_round.questions)
    return "některé povinné položky"


def _step_matches() -> None:
    result = GenericResult.model_validate(st.session_state["generic_result"])
    st.markdown(f"### ✅ Profil zpracován — {TYPE_BADGE.get(result.profile.candidate_type, '')}")
    st.caption(
        "Našli jsme tyto vhodné pozice. Vyber tu, o kterou máš zájem, " "nebo počkej na další."
    )

    if not result.matches:
        st.info("Žádné vhodné pozice momentálně. Zkus to později.")
        if st.button("↩︎ Nahrát jiné CV"):
            _reset()
            st.rerun()
        return

    for i, match in enumerate(result.matches):
        ad = next((a for a in result.matched_ads if a.id == match.ad_id), None)
        if ad is None:
            continue
        with st.container():
            st.markdown(f"**{ad.title}** — {ad.employer or '—'} · {ad.location} · {ad.level}")
            st.caption(_match_reasoning_line(match))
            c1, c2 = st.columns(2)
            if c1.button("✅ Mám zájem", key=f"interest_{i}"):
                _go_interested(result.candidate_id, match.ad_id)
            if c2.button("⏳ Počkám na další pozici", key=f"wait_{i}"):
                express_interest(result.candidate_id, match.ad_id, "wait")
                st.info(
                    "OK. Jakmile přijde další vhodná pozice, dáme vědět e-mailem. "
                    "_(V MVP e-maily neodesíláme — informativní text.)_"
                )
            st.markdown("---")

    if st.button("↩︎ Nahrát jiné CV"):
        _reset()
        st.rerun()


def _match_reasoning_line(match) -> str:
    import json

    if not match.reasoning:
        return f"Celkový fit (vidí recruiter): skryté · pozice ad #{match.ad_id}"
    try:
        payload = json.loads(match.reasoning)
        return "Proč ti sedne: " + str(payload.get("verdict", ""))[:240]
    except (json.JSONDecodeError, TypeError):
        return "Proč ti sedne: " + str(match.reasoning)[:240]


def _go_interested(candidate_id: int, ad_id: int) -> None:
    with st.spinner("Připravuji otázky k pozici…"):
        try:
            interest = express_interest(candidate_id, ad_id, "interested")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Chyba: {exc}")
            return
    st.session_state["selected_ad_id"] = ad_id
    st.session_state["interest_result"] = interest.model_dump()
    st.session_state["cand_step"] = "role_form"
    st.rerun()


def _step_role_form() -> None:
    interest = InterestResult.model_validate(st.session_state["interest_result"])
    st.markdown("### 📝 Pár otázek k pozici")
    st.caption(
        "Některé odpovědi jsme za tebe předvyplnili z CV — zkontroluj je, "
        "uprav nebo nech být. Otázky jsou stejné pro všechny uchazeče."
    )

    with st.form("role_form"):
        inputs: dict[str, str] = {}
        prefilled_defaults: dict[str, str] = {}
        for q in interest.prefilled_questions:
            default = q.prefilled_answer or ""
            prefilled_defaults[q.slot] = default
            label = q.question_text
            if q.prefilled_answer:
                label += "  · 🤖 AI návrh — můžeš upravit"
            else:
                label += "  · ✍️ doplň prosím"
            inputs[q.slot] = st.text_area(label, value=default, key=f"rf_{q.slot}")
        submitted = st.form_submit_button("Odeslat přihlášku", type="primary")

    if submitted:
        prefilled_set = {s for s, d in prefilled_defaults.items() if d}
        edited_set = {
            s
            for s in inputs
            if prefilled_defaults.get(s) and inputs[s].strip() != prefilled_defaults[s].strip()
        }
        with st.spinner("Ukládám a vyhodnocuji…"):
            try:
                result = submit_role_specific(
                    interest.candidate_id,
                    interest.ad_id,
                    answers={s: v.strip() for s, v in inputs.items()},
                    prefilled_set=prefilled_set,
                    edited_set=edited_set,
                )
            except Exception as exc:  # noqa: BLE001
                st.error(f"Chyba při ukládání: {exc}")
                return
        st.session_state["final_result"] = result.model_dump()
        st.session_state["cand_step"] = "done"
        st.rerun()


def _step_done() -> None:
    st.markdown("### 🎉 Přihláška odeslána")
    st.success(
        "Tvé CV a odpovědi jsou uloženy. Recruiter je teď vidí v záložce "
        "**🧑‍💼 Recruiter** (včetně skóre a zdůvodnění — ta se kandidátovi "
        "nezobrazují)."
    )
    st.caption(
        "Přepni nahoře na záložku **Recruiter** a najdeš svou kartu v " "příslušném sloupci."
    )
    if st.button("↩︎ Nahrát další CV"):
        _reset()
        st.rerun()
