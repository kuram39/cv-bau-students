"""Recruiter panel — one target job, two ranked candidate columns.

Reads everything from `candidates.repo` (interested candidates with a
Match row for the target ad). Left column = students-with-potential,
right column = experienced. Each row expands into a drill-in with the
score breakdown, bridge plan, translated capabilities, and the
role-specific Q&A the candidate submitted.
"""

from __future__ import annotations

import streamlit as st

from cv_bau_students.analytics.audit import audit_by_type, audit_csv
from cv_bau_students.candidates import repo as candidates_repo
from cv_bau_students.evidence import TIER_EMOJI, doloznost_label
from cv_bau_students.explanation.format import parse_reasoning
from cv_bau_students.jobads import repo as jobads_repo
from cv_bau_students.matcher.score import bridge_estimate, counterfactual_lifts
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
    # Decision-support + transparency framing (EU AI Act high-risk / GDPR Art. 22).
    st.info(
        "ℹ️ Skóre = **podpora rozhodování**, ne automatické odmítnutí — finální "
        "rozhodnutí je na tobě. Hodnotíme **dovednosti** (pokrytí cílové sady), "
        "ne osobní údaje. Dovednosti z CV jsou **self-reported, neověřené**; "
        '„doloženost" ukazuje, jak je kandidát doložil (práce/projekt vs jen uvedeno). '
        "Metoda + limity: viz `docs/MODEL_CARD.md`."
    )
    _render_job_description(target_ad)
    _render_target_skill_picker(target_ad)

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

    _render_audit(target_ad.id)

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


def _render_audit(ad_id: int) -> None:
    """Selection-rate disclosure across candidate types (research #8). A
    DISCLOSURE metric, not a pass/fail bar — the demo collects no protected
    attributes, so this is auditability-by-design, not an adverse-impact audit."""
    with st.expander("📊 Audit — doložitelnost skóre napříč typy kandidátů"):
        report = audit_by_type(ad_id)
        if not report["total"]:
            st.caption("Zatím žádní kandidáti k auditu.")
            return
        st.caption(
            f"Výběr = skóre ≥ {report['threshold']:.0f} %. "
            "Metrika transparentnosti, ne automatické rozhodnutí (viz `docs/MODEL_CARD.md`)."
        )
        rows = [
            {
                "typ": g,
                "n": row["n"],
                "vybráno": row["selected"],
                "míra výběru": row["selection_rate"],
                "průměrné pokrytí %": row["mean_coverage"],
            }
            for g, row in report["groups"].items()
        ]
        st.table(rows)
        ratio = report["four_fifths_ratio"]
        if ratio is not None:
            msg = f"Four-fifths poměr: **{ratio}**"
            if report["adverse_impact"]:
                st.warning(msg + " — < 0,80 → **prověř** rozložení (ne automatická akce).")
            else:
                st.caption(msg + " (≥ 0,80).")
        else:
            st.caption("Four-fifths poměr: nelze spočítat (málo dat / jen jedna skupina).")
        st.download_button(
            "⬇️ Stáhnout audit (CSV)",
            data=audit_csv(report),
            file_name=f"audit_ad_{ad_id}.csv",
            mime="text/csv",
        )


def _render_job_description(target_ad: JobAd) -> None:
    """Collapsed job-description detail, shown right under the ad header."""
    with st.expander("📋 Popis pozice (rozbal pro detail inzerátu)"):
        st.markdown(f"**Must-have:** {', '.join(target_ad.must_have) or '—'}")
        st.markdown(f"**Nice-to-have:** {', '.join(target_ad.nice_to_have) or '—'}")
        langs = ", ".join(f"{lr.language} ({lr.min_level})" for lr in target_ad.languages_required)
        st.markdown(f"**Jazyky:** {langs or '—'}")
        st.markdown("**Text inzerátu:**")
        st.write(target_ad.raw_text)


def _render_target_skill_picker(ad: JobAd) -> None:
    """Recruiter curates the role's base-case target skill set.

    This is THE comparator: the recruiter picks the skills that matter for the
    position (shared base for students and experienced alike), and everyone is
    scored on coverage of that set — not on years of experience. A one-click
    **base preset** seeds a sensible starting set; the recruiter then tweaks.

    Options pool = ISCO occupation skills ∪ the ad's must/nice ∪ the preset,
    all candidate-aligned (ESCO ids), so saving a skill actually scores.
    Saving (or applying the preset) re-scores every candidate immediately —
    deterministic, no LLM.
    """
    with st.expander("🎯 Cílové dovednosti pro tuto roli (editace náboráře)", expanded=True):
        st.caption(
            "Vyber dovednosti, které pro tuto roli skutečně vyžaduješ — to je "
            "**základní porovnávací osa** mezi studenty a experienced. **Core** = klíčové, "
            "**Optional** = výhodou. Skóre uchazečů = pokrytí tohoto výběru."
        )

        if st.button("✨ Načíst doporučené base dovednosti", key=f"preset_{ad.id}"):
            preset = jobads_repo.apply_base_preset(ad.id)
            if preset["core"] or preset["optional"]:
                n = candidates_repo.rescore_ad(ad.id)
                st.success(
                    f"Base preset uložen: {len(preset['core'])} core + "
                    f"{len(preset['optional'])} optional. Přepočítáno {n} kandidátů."
                )
                st.rerun()
            else:
                # apply_base_preset is a no-op when nothing resolves → the
                # recruiter's existing manual curation is left intact.
                st.warning(
                    "Pro tuto pozici nešlo z inzerátu/ISCO odvodit žádné rozpoznané "
                    "base dovednosti. Stávající výběr ponechán beze změny — vyber ručně níže."
                )

        opts = jobads_repo.target_skill_options(ad.id)
        if not opts["core"] and not opts["optional"]:
            st.caption(
                "Pro tento inzerát není rozpoznané ISCO povolání ani rozpoznané "
                "dovednosti — není z čeho vybírat. Spusť `resolve_ad_isco` (seed) "
                "nebo doplň ISCO kód inzerátu."
            )
            return

        name_to_id = {name: sid for sid, name in (opts["core"] + opts["optional"])}
        core_opts = [name for _, name in opts["core"]]
        opt_opts = [name for _, name in opts["optional"]]
        core_set, opt_set = set(core_opts), set(opt_opts)

        current = jobads_repo.get_target_skills(ad.id) or {"core": set(), "optional": set()}
        id_to_name = {sid: name for name, sid in name_to_id.items()}
        # Defaults must be a subset of each multiselect's own options, else
        # Streamlit raises. target_skill_options keeps curated tiers consistent;
        # this filter is the belt-and-suspenders guard.
        core_default = [
            n for i in current.get("core", set()) if (n := id_to_name.get(i)) in core_set
        ]
        opt_default = [
            n for i in current.get("optional", set()) if (n := id_to_name.get(i)) in opt_set
        ]

        # st.form batches the multiselects: editing them does NOT rerun the app
        # (no candidate re-render / recompute). Scoring runs ONLY on submit.
        with st.form(key=f"target_skills_form_{ad.id}"):
            chosen_core = st.multiselect("Core dovednosti", core_opts, default=core_default)
            chosen_opt = st.multiselect("Optional dovednosti", opt_opts, default=opt_default)
            submitted = st.form_submit_button(
                "💾 Uložit cílové dovednosti",
                type="primary",
                help=(
                    "Uložením se přepočítají skóre VŠECH uchazečů — každé CV se "
                    "znovu vyhodnotí (rekvalifikuje) proti tomuto výběru cílových "
                    "dovedností. Dokud neuložíš, změny výběru výše se neprojeví."
                ),
            )
        if submitted:
            jobads_repo.set_target_skills(
                ad.id,
                core=[name_to_id[n] for n in chosen_core if n in name_to_id],
                optional=[name_to_id[n] for n in chosen_opt if n in name_to_id],
            )
            n = candidates_repo.rescore_ad(ad.id)
            if not chosen_core and not chosen_opt:
                # Empty selection = no curation → matcher falls back to the ad's
                # must + nice-to-have as the coverage target.
                st.info(
                    "Prázdný výběr — kurátorská sada zrušena. Skóre použije "
                    f"must + nice-to-have z inzerátu. Přepočítáno {n} kandidátů."
                )
            else:
                st.success(
                    f"Uloženo: {len(chosen_core)} core + {len(chosen_opt)} optional. "
                    f"Přepočítáno {n} kandidátů."
                )
            st.rerun()


def _render_column(ad_id: int, *, kind: str) -> None:
    summaries = candidates_repo.get_candidates_for_ad(ad_id, kind=kind)
    if not summaries:
        st.caption("_(zatím žádní zájemci v této kategorii)_")
        return
    for summary in summaries:
        _render_candidate_row(ad_id, summary)


def _render_candidate_row(ad_id: int, summary) -> None:
    """One compact, collapsible list row per candidate. The header line is the
    whole scannable summary (badge · name · coverage % · doloženost); progress
    bar, top skills, the AI headline and the full drill-in live inside the
    expander so the page reads as a list, not a stack of blocks.

    'Doloženost' = evidence strength of the matched skills (how they were
    demonstrated — work/project vs claimed), NOT LLM self-confidence."""
    badge = TYPE_BADGE.get(summary.kind, "❓")
    label = (
        f"{badge} · {summary.display_name} · {summary.total:.0f} % · "
        f"doloženost: {summary.doloznost}"
    )
    with st.expander(label):
        st.progress(min(1.0, summary.total / 100))
        if summary.top_skills:
            st.caption("🏷 " + " · ".join(summary.top_skills))
        if summary.headline:
            st.caption(summary.headline)
        _render_detail(ad_id, summary.candidate_id)
        st.markdown("---")


def _render_detail(ad_id: int, candidate_id: int) -> None:
    detail = candidates_repo.get_candidate_detail(candidate_id, ad_id)
    if detail is None:
        st.caption("_(detail nedostupný)_")
        return

    m = detail.match
    # Headline = skill coverage. Bridge = secondary "potential/growth" signal.
    # personal_fit retired (not shown).
    c1, c2 = st.columns(2)
    c1.metric("Skill coverage", f"{m.skill_fit:.0f} %")
    # Bridge as a graspable "how long to ready this candidate" estimate in months,
    # not the abstract 0–100 index. bridge_fit < 0 → no rubric → N/A.
    if m.bridge_fit < 0:
        c2.metric("Odhad doučení do role", "N/A", help="pro tuto doménu/úroveň není rubrika")
    else:
        est = bridge_estimate(m.bridge_plan)
        if est["gaps"] == 0:
            c2.metric("Odhad doučení do role", "0 měs.", help="pokrývá rubriku — připraven hned")
        elif est["bridgeable"] and est["experience_only"]:
            c2.metric(
                "Odhad doučení do role",
                f"~{est['months']} měs. + praxe",
                help="část mezer se nedá zkrátit kurzem/projektem — jen reálnou praxí",
            )
        elif est["bridgeable"]:
            c2.metric(
                "Odhad doučení do role",
                f"~{est['months']} měs.",
                help="odhad doučení chybějících dovedností na úroveň pozice",
            )
        else:
            c2.metric(
                "Odhad doučení do role",
                "jen praxí",
                help="chybějící dovednosti vyžadují reálnou praxi — bez zkratky",
            )

    # Honest precision (research #8): when the matched skills are mostly *claimed*
    # (weak evidence) rather than demonstrated, flag the coverage as orientational.
    # Driven by evidence strength (source_type tiers) — the product's doloženost
    # concept — NOT translator confidence (evidence.py keeps these distinct).
    matched_evidence = getattr(m.skill_fit_detail, "matched_evidence", None) or []
    if matched_evidence and doloznost_label([t for _, t in matched_evidence]) == "nízká":
        st.warning(
            "⚠️ Nízká doloženost — pokryté dovednosti jsou převážně jen uvedené "
            "(ne prokázané praxí/projektem). Skóre ber jako orientační, opři "
            "rozhodnutí o důkazy níže."
        )

    _render_skill_fit_detail(m.skill_fit_detail)
    st.caption(
        "ℹ️ Rozpoznání českých dovedností je omezené → seznam chybějících dovedností "
        "může být neúplný. Viz `docs/MODEL_CARD.md`."
    )

    if m.bridge_plan:
        est = bridge_estimate(m.bridge_plan)
        summ = f"~{est['months']} měs. doučení"
        if est["experience_only"]:
            summ += f" + {est['experience_only']} dovedností jen praxí"
        st.markdown(f"**Plán doučení** — {summ} (co doplnit na úroveň pozice):")
        for gap in m.bridge_plan:
            when = (
                f"~{gap.bridgeable_in_months} měs."
                if gap.bridgeable_in_months is not None
                else "🚫 jen praxí — bez zkratky"
            )
            st.caption(f"• {gap.skill} — {when}")

    if detail.capabilities:
        st.markdown("**Přeložené schopnosti:**")
        for cap in detail.capabilities[:8]:
            caveat = f" — _{cap.caveat}_" if cap.caveat else ""
            st.caption(
                f"• **{cap.skill}** ({cap.confidence:.0%}, {cap.source_type}): "
                f"„{cap.evidence_quote}“{caveat}"
            )

    # AI verdict directly under the score breakdown + capabilities it reasons over.
    if m.reasoning:
        _render_reasoning(m.reasoning)

    # The candidate's own questionnaire answers sit at the end — supporting
    # detail the recruiter reads after the verdict, just above the raw sources.
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

    # Human-oversight affordance after the verdict + answers, before raw sources.
    _render_override_control(ad_id, candidate_id, detail)

    if detail.raw_cv_text:
        with st.expander("📄 Původní CV (raw text)"):
            st.text(detail.raw_cv_text)

    with st.expander("🔧 Raw profil JSON"):
        st.json(detail.profile.model_dump())


def _render_override_control(ad_id: int, candidate_id: int, detail) -> None:
    """Human-oversight affordance (EU AI Act Art. 14 / GDPR Art. 22): let the
    recruiter contest / override the score, recording a note. The friction of an
    explicit decision is what makes the human-in-the-loop real (research #8)."""
    with st.expander("⚖️ Lidský dohled — potvrdit / přepsat skóre"):
        if detail.recruiter_override is not None:
            state = (
                "❌ označeno jako nesprávné párování"
                if detail.recruiter_override
                else "✅ skóre potvrzeno"
            )
            when = detail.decision_at.strftime("%Y-%m-%d %H:%M") if detail.decision_at else "—"
            st.caption(f"Poslední rozhodnutí: {state} · {when}")
            if detail.override_note:
                st.caption(f"Poznámka: {detail.override_note}")
        with st.form(key=f"override_{ad_id}_{candidate_id}"):
            flag = st.checkbox(
                "Označit jako nesprávné párování (přepsat skóre)",
                value=bool(detail.recruiter_override),
            )
            note = st.text_area("Poznámka (důvod rozhodnutí)", value=detail.override_note or "")
            if st.form_submit_button("💾 Uložit rozhodnutí"):
                candidates_repo.set_match_override(candidate_id, ad_id, override=flag, note=note)
                st.success("Rozhodnutí uloženo (lidský dohled).")
                st.rerun()


def _render_reasoning(raw: str) -> None:
    """Structured AI verdict: headline verdict + strengths / gaps / interview
    prompts. Tolerant of truncated/invalid JSON (never dumps raw JSON)."""
    r = parse_reasoning(raw)
    st.markdown("**Zdůvodnění (AI):**")
    if r["verdict"]:
        st.info(r["verdict"])
    for label, key, marker in (
        ("✅ Silné stránky", "strengths", "🟢"),
        ("⚠️ Mezery", "gaps", "🔴"),
        ("❓ Otázky na pohovor", "interview_prompts", "❓"),
    ):
        items = r.get(key) or []
        if items:
            st.markdown(f"**{label}:**")
            for item in items:
                st.markdown(f"- {marker} {item}")
    if r["truncated"]:
        st.caption("_(zdůvodnění bylo uloženo neúplné — přegeneruj re-runem analýzy)_")


def _render_skill_fit_detail(d) -> None:
    """Why skill_fit is what it is: must/nice coverage + ESCO role match."""
    if d is None:
        return
    matched_must = ", ".join(d.matched_must) or "—"
    matched_nice = ", ".join(d.matched_nice) or "—"
    st.caption(f"✅ Must: {matched_must} · Nice: {matched_nice}")
    if d.missing_must:
        st.caption(f"❌ Chybí must: {', '.join(d.missing_must)}")

    # Headline coverage: which target-skill set drove the % + matched/missing.
    if d.role_essential_total:
        src = {
            "curated": "náborářem vybrané cílové dovednosti",
            "must_nice": "must + nice-to-have z inzerátu",
        }.get(d.target_source, "cílové dovednosti")
        st.caption(
            f"🎯 Skill coverage — {d.role_essential_evidenced}/{d.role_essential_total} " f"({src})"
        )
        # Per-skill evidence strength: how each matched skill was demonstrated
        # (work/project vs claimed) — not LLM self-confidence.
        evidence = getattr(d, "matched_evidence", None) or []
        if evidence:
            tags = " · ".join(f"{TIER_EMOJI.get(tier, '⚪')} {name}" for name, tier in evidence)
            st.markdown("**Pokryté dovednosti (doloženost):** " + tags)
            st.caption("🟢 prokázané praxí · 🟡 projekt/studium · ⚪ jen uvedeno")
        elif d.role_essential_matched:
            st.markdown("**Pokryté:** " + " · ".join(d.role_essential_matched))
        # Gaps at EQUAL prominence with matched (research #8: disconfirmation-
        # inviting design) — promoted from a trailing caption to a markdown block.
        if d.role_essential_missing:
            st.markdown("**❌ Chybějící (ukázka):** " + " · ".join(d.role_essential_missing))
        # Counterfactual recourse: what each gap would do to coverage if evidenced.
        for skill, cur, new in counterfactual_lifts(d):
            st.markdown(f"↗️ Doložit **{skill}** → pokrytí {cur} % → **{new} %**")
