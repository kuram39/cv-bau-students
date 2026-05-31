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

from cv_bau_students.models import GenericResult, InterestResult, JobAd
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

# Tweet-length cap per role-question answer; enforced as a hard filter on submit.
MAX_ANSWER_CHARS = 280


def render_candidate_panel(target_ad: JobAd | None = None) -> None:
    """Single-target demo: every uploaded CV is matched against ONE
    pre-selected position (`target_ad`). The candidate expresses interest in
    that role only — so they always land in the recruiter view for it.
    Corpus-wide ranking is above MVP scope.
    """
    if target_ad is None:
        st.warning(
            "Cílová pozice není v databázi. Spusť seed "
            "(`python -m scripts.seed_target_demo`) a obnov stránku."
        )
        return
    # Stash the target ad so the step functions (which run on later reruns) see it.
    st.session_state["target_ad"] = target_ad.model_dump()

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


def _target_ad() -> JobAd:
    return JobAd.model_validate(st.session_state["target_ad"])


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
    ad = _target_ad()
    st.markdown(f"### ✅ Profil zpracován — {TYPE_BADGE.get(result.profile.candidate_type, '')}")
    st.caption("Tvůj profil porovnáváme s touto otevřenou pozicí:")

    # Preview line for the target ad: reuse its match if the generic pass
    # surfaced it; otherwise show a neutral line (the recruiter view re-scores).
    target_match = next((m for m in result.matches if m.ad_id == ad.id), None)
    with st.container():
        st.markdown(f"**{ad.title}** — {ad.employer or '—'} · {ad.location} · {ad.level}")
        if target_match is not None:
            st.caption(_match_reasoning_line(target_match))
        c1, c2 = st.columns(2)
        if c1.button("✅ Mám zájem o tuto pozici", type="primary", key="interest_target"):
            _go_interested(result.candidate_id, ad.id)
        if c2.button("🔎 Mám zájem o jinou nabídku", key="interest_other"):
            express_interest(result.candidate_id, ad.id, "wait")
            st.info(
                "OK — tuto pozici přeskakujeme. Jakmile přibude jiná vhodná nabídka, "
                "dáme vědět e-mailem. _(V tomto demu nabízíme jen tuto jednu pozici; "
                "e-maily neodesíláme — informativní text.)_"
            )
        st.markdown("---")

    if st.button("↩︎ Nahrát jiné CV"):
        _reset()
        st.rerun()


def _match_reasoning_line(match) -> str:
    import json

    if not match.reasoning:
        # No LLM verdict at preview time (deferred to express-interest) — build a
        # deterministic "why it fits" from the matcher's own skill_fit_detail.
        d = getattr(match, "skill_fit_detail", None)
        if d is not None:
            hit = ", ".join((d.matched_must + d.matched_nice)[:4]) or "—"
            parts = [f"Sedí: {hit}"]
            if d.missing_must:
                parts.append(f"chybí: {', '.join(d.missing_must[:3])}")
            if d.role_essential_total:
                parts.append(f"role {d.role_essential_evidenced}/{d.role_essential_total}")
            return "Proč ti sedne — " + " · ".join(parts)
        return f"Skill fit: {match.skill_fit:.0f}/100 · pozice ad #{match.ad_id}"
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
        "Tyto doplňující otázky pomáhají odhalit dovednosti, které z CV nemusí "
        "být patrné. Odpověz vlastními slovy, **stručně — max "
        f"{MAX_ANSWER_CHARS} znaků** na odpověď (jako tweet). Otázky jsou stejné "
        "pro všechny uchazeče. **Vyplň všechny** — bez toho přihlášku nelze odeslat."
    )

    with st.form("role_form"):
        inputs: dict[str, str] = {}
        prefilled_defaults: dict[str, str] = {}
        for q in interest.prefilled_questions:
            default = q.prefilled_answer or ""
            prefilled_defaults[q.slot] = default
            inputs[q.slot] = st.text_area(
                q.question_text,
                value=default,
                key=f"rf_{q.slot}",
                max_chars=MAX_ANSWER_CHARS,
                help=f"Max {MAX_ANSWER_CHARS} znaků.",
            )
        submitted = st.form_submit_button("Odeslat přihlášku", type="primary")

    if submitted:
        stripped = {s: v.strip() for s, v in inputs.items()}
        # Hard filter: every question required + max length enforced.
        missing = [s for s, v in stripped.items() if not v]
        too_long = [s for s, v in stripped.items() if len(v) > MAX_ANSWER_CHARS]
        if missing:
            st.error(
                f"Vyplň prosím všechny otázky ({len(missing)} zatím prázdná) — "
                "přihlášku nelze odeslat s prázdnou odpovědí."
            )
            return
        if too_long:
            st.error(f"Některé odpovědi přesahují {MAX_ANSWER_CHARS} znaků. Zkrať je.")
            return

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
