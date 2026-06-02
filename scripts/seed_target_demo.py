#!/usr/bin/env python3
"""Seed the single-target-job demo: one ad + N pre-walked candidates.

Pipeline (all LLM-backed steps require ANTHROPIC_API_KEY — run this
yourself, the agent harness scrubs the key):

  1. Resolve the target ad ("Datový analytik") and turn it into the demo
     role in place: rename the employer to a made-up firm, lightly
     paraphrase the opening, and enrich the (empty-from-scrape) skill
     lists with realistic data-analyst must/nice-to-have skills +
     a Czech language requirement. Idempotent — skips if already done.
  2. Generate the role-specific question template ONCE (LLM). Every
     candidate then answers the same questions.
  3. For each CV in data/raw_cv_samples/{students,experienced}/:
       - run_generic_pass  → candidate persisted (extract + translate only)
       - express_interest('interested') → AI questionnaire (questions only)
       - submit_role_specific(..., answers={}) → score + reason the Match.
         No AI-drafted answers (the questionnaire is left blank in the seed).
  4. Print a per-CV summary.

Idempotent: cv_hash dedup means re-running updates rather than
duplicates. Safe to re-run after adding more sample CVs.

Usage:
    python -m scripts.seed_target_demo
    python -m scripts.seed_target_demo --target-title "Datový analytik"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from cv_bau_students.jobads.repo import (
    find_ad_by_title_substring,
    resolve_ad_isco,
    set_ad_fields_and_skills,
)
from cv_bau_students.models import LanguageRequirement
from cv_bau_students.pipeline import (
    express_interest,
    run_generic_pass,
    submit_role_specific,
)

load_dotenv()

STUDENTS_DIR = Path("data/raw_cv_samples/students")
EXPERIENCED_DIR = Path("data/raw_cv_samples/experienced")

DEMO_EMPLOYER = "ApexFinance s.r.o."
DEMO_MUST_HAVE = ["SQL", "Python", "Power BI", "Excel"]
DEMO_NICE_TO_HAVE = ["Tableau", "statistics"]
DEMO_LANGUAGES = [LanguageRequirement(language="Czech", min_level="C1")]

# Full, realistic target-ad text for the demo — composed from the real scraped
# data-analyst ads (jobs.cz), re-employer'd to our fictional firm. The original
# scraped "Datový analytik" row was a 299-char stub; this gives the recruiter +
# the reasoning LLM a complete BI/finance job description aligned to the demo's
# must/nice (SQL, Python, Power BI, Excel · Tableau, statistika).
DEMO_RAW_TEXT = (
    f"Společnost {DEMO_EMPLOYER} hledá datového analytika / datovou analytičku "
    "do interního týmu Business Intelligence. Jsme finanční skupina a data jsou "
    "jádrem našeho rozhodování — od každodenní operativy až po strategické kroky "
    "vedení. Hledáme člověka, který má rád práci s daty, rozumí informačním "
    "potřebám byznysu a nebojí se „zašpinit si ruce“ jejich realizací.\n\n"
    "Co u nás budeš dělat:\n"
    "• Připravovat a vyhodnocovat data z interních systémů — psát a optimalizovat "
    "SQL dotazy, čistit a transformovat data do podoby vhodné pro analýzu.\n"
    "• Navrhovat datové modely a stavět reporting v Power BI (sémantický model, "
    "DAX, Power Query) i ad-hoc analýzy v Excelu; část dashboardů udržujeme v "
    "Tableau.\n"
    "• Provádět statistické analýzy a prediktivní výpočty v Pythonu "
    "(pandas, NumPy) a interpretovat výsledky pro netechnické publikum.\n"
    "• Vést workshopy s business uživateli, odhalovat jejich informační potřeby a "
    "spolu s nimi definovat klíčové metriky a KPI.\n"
    "• Prezentovat zjištění na úrovni vedení a podporovat self-service BI napříč "
    "odděleními.\n"
    "• Dokumentovat datové toky, transformace a navržená řešení.\n\n"
    "Koho hledáme:\n"
    "• Solidní znalost SQL (dotazování, joiny, agregace) a praktickou zkušenost s "
    "reportingem v Power BI.\n"
    "• Schopnost pracovat s daty v Pythonu (pandas/NumPy) a provádět i "
    "interpretovat statistické analýzy.\n"
    "• Pokročilý Excel (kontingenční tabulky, vzorce) a cit pro datovou "
    "vizualizaci.\n"
    "• Porozumění datovému modelování a chuť rozumět byznysu za daty.\n"
    "• Komunikativnost, pečlivost a schopnost vysvětlit složitá data srozumitelně.\n"
    "• Čeština na úrovni C1; angličtinu využiješ při čtení dokumentace.\n\n"
    "Výhodou:\n"
    "• Zkušenost s Tableau, se statistikou/strojovým učením, s časovými řadami.\n"
    "• Práce s velkými daty, cloudovými platformami (Snowflake, Databricks) a "
    "verzováním (Git).\n\n"
    "Nabízíme:\n"
    "• Roli v BI týmu finanční skupiny s reálným dopadem na rozhodování firmy.\n"
    "• 25 dní dovolené, pružnou pracovní dobu, sick days.\n"
    "• Roční příspěvek 12 000 Kč do cafeterie, příspěvek na stravování, podporu "
    "vzdělávání a firemní akce.\n"
)


def _modify_target_ad(ad) -> None:
    """Turn the scraped row into the demo target — idempotent."""
    if ad.employer == DEMO_EMPLOYER:
        # Already prepared by an earlier run. Still realign the domain: a DB
        # prepared before the domain fix kept domain="general" (no rubric →
        # bridge_fit N/A), and the full modify is skipped here.
        if ad.domain != "data-analyst":
            set_ad_fields_and_skills(ad.id, domain="data-analyst")
            print(f"  target ad {ad.id} already prepared — realigned domain → data-analyst.")
        else:
            print(f"  target ad {ad.id} already prepared — skipping modify.")
        return
    set_ad_fields_and_skills(
        ad.id,
        employer=DEMO_EMPLOYER,
        raw_text=DEMO_RAW_TEXT,
        # Scrape classified the ad as "general"; align it with the
        # data-analyst level_checklists rubric so bridge_fit computes
        # (instead of the -1.0 / "N/A" sentinel for an uncovered domain).
        domain="data-analyst",
        must_have=DEMO_MUST_HAVE,
        nice_to_have=DEMO_NICE_TO_HAVE,
        languages_required=DEMO_LANGUAGES,
    )
    print(
        f"  modified ad {ad.id}: employer={DEMO_EMPLOYER}, "
        f"must_have={DEMO_MUST_HAVE}, nice={DEMO_NICE_TO_HAVE}"
    )


def _process_cv(path: Path, ad) -> dict:
    """Walk one CV through the interested journey. Returns a summary.

    No AI-drafted answers: the AI value is the questions (generated once per
    ad). The seed submits empty answers — the Match is still scored + reasoned,
    matching the live flow before a candidate types their answers.
    """
    file_bytes = path.read_bytes()
    gen = run_generic_pass(file_bytes, path.name, target_ad=ad)
    if gen.status == "needs_completion":
        return {
            "file": path.name,
            "status": "needs_completion",
            "candidate_id": gen.candidate_id,
            "note": "BAU-mandatory fields missing; skipped role-specific.",
        }

    express_interest(gen.candidate_id, ad.id, "interested")  # ensures + caches the AI questions

    result = submit_role_specific(
        gen.candidate_id,
        ad.id,
        answers={},  # seed leaves the questionnaire blank (no AI-fabricated answers)
        prefilled_set=set(),
        edited_set=set(),
    )
    return {
        "file": path.name,
        "status": "matched",
        "candidate_id": gen.candidate_id,
        "kind": gen.profile.candidate_type,
        "total": round(result.match.total, 1),
        "skill_fit": round(result.match.skill_fit, 1),
        "bridge_fit": round(result.match.bridge_fit, 1),
        "personal_fit": round(result.match.personal_fit, 1),
    }


def run_seed(target_title: str = "Datový analytik") -> int:
    """Core seed routine — argv-free so tests can drive it."""
    ad = find_ad_by_title_substring(target_title)
    if ad is None:
        print(
            f"No ad matching {target_title!r}. Is the DB seeded? "
            f"Run ensure_seeded() / load the scraped ads first.",
            file=sys.stderr,
        )
        return 1
    print(f"Target ad: id={ad.id} title={ad.title!r}")
    _modify_target_ad(ad)

    # Resolve the ad to an ISCO occupation for target-role-first scoring.
    # Lexical hit ("Datový analytik" → "analytik dat" → 2511) is free; an
    # unrecognised title falls back to one cheap LLM call.
    isco_code, isco_label, isco_method = resolve_ad_isco(ad.id)
    print(f"  ISCO: {isco_code} ({isco_label}) via {isco_method}")

    # Apply the base-skill preset so the demo's coverage headline is meaningful
    # out of the box (recruiter can still edit it in the UI skill-picker). The
    # preset is candidate-aligned, so every applicant is scored on the same
    # base set — the comparator between students and experienced.
    from cv_bau_students.jobads.repo import apply_base_preset

    preset = apply_base_preset(ad.id)
    print(
        f"  base preset: {len(preset['core'])} core + {len(preset['optional'])} optional "
        f"target skills (curated set for coverage scoring)"
    )

    # Refresh the ad (employer/skills/isco changed) for the Q generator.
    ad = find_ad_by_title_substring(target_title)

    # Generate the fixed role-specific question template once.
    from cv_bau_students.pipeline import ensure_role_specific_questions

    questions = ensure_role_specific_questions(ad.id)
    print(f"  role-specific questions ({len(questions)}):")
    for q in questions:
        print(f"    - [{q.slot}] {q.question_text}")

    cv_paths = sorted(STUDENTS_DIR.glob("*.txt")) + sorted(EXPERIENCED_DIR.glob("*.txt"))
    if not cv_paths:
        print(
            f"No CV samples in {STUDENTS_DIR} / {EXPERIENCED_DIR}. "
            f"Run scripts/generate_student_cvs.py + fetch_hf_resume_samples.py, "
            f"or use the committed demo set.",
            file=sys.stderr,
        )
        return 1

    print(f"\nProcessing {len(cv_paths)} CV(s)...")
    summaries = []
    for path in cv_paths:
        try:
            summary = _process_cv(path, ad)
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED {path.name}: {exc}", file=sys.stderr)
            continue
        summaries.append(summary)
        if summary["status"] == "matched":
            print(
                f"  {path.name}: {summary['kind']} total={summary['total']} "
                f"(skill={summary['skill_fit']} bridge={summary['bridge_fit']} "
                f"personal={summary['personal_fit']})"
            )
        else:
            print(f"  {path.name}: {summary['status']} — {summary.get('note', '')}")

    matched = [s for s in summaries if s["status"] == "matched"]
    print(f"\nDone. {len(matched)}/{len(cv_paths)} candidates matched + stored for ad {ad.id}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed the single-target demo.")
    parser.add_argument("--target-title", type=str, default="Datový analytik")
    args = parser.parse_args()
    return run_seed(args.target_title)


if __name__ == "__main__":
    sys.exit(main())
