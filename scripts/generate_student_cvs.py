#!/usr/bin/env python3
"""Generate Czech student-track CV samples via the LLM.

Three hand-curated personas (briefs below) → one LLM call each → a
realistic structured Czech CV written to
`data/raw_cv_samples/students/persona_{name}.txt`.

These are the "students-with-potential" half of the demo: data-analyst-
adjacent profiles where the candidate has academic + brigáda signal but
no full work history — exactly the bridge-plan case the product exists
for.

Idempotent: skips a persona whose output file already exists unless
`--force` is passed (so re-running the seed doesn't re-spend tokens).

Usage:
    python -m scripts.generate_student_cvs
    python -m scripts.generate_student_cvs --force
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from cv_bau_students import llm

load_dotenv()

OUT_DIR = Path("data/raw_cv_samples/students")

# Persona briefs. Each is data-analyst-adjacent but with a different mix
# of academic depth, brigáda relevance, and tooling — so the recruiter
# ranked list shows spread, not three near-identical scores.
PERSONAS: dict[str, str] = {
    "anna": (
        "Anna Nováková, 22 let, Praha. Studuje 3. ročník bakaláře "
        "'Aplikovaná informatika' na VŠE Praha (dokončení 2026). "
        "Bakalářská práce: regresní analýza chování zákazníků v e-shopu "
        "(Python, pandas, scikit-learn). Brigáda: 2 roky pokladní v "
        "McDonald's (práce pod tlakem, týmová spolupráce). Hard skills: "
        "Python (pandas, numpy), SQL základy, Excel (kontingenční "
        "tabulky), základy statistiky. Soft skills: komunikace, "
        "spolehlivost, práce v týmu. Jazyky: čeština rodný, angličtina "
        "B2. Bez reálné pracovní zkušenosti v oboru — pouze škola + "
        "brigáda. Hledá juniorní datařskou pozici."
    ),
    "jakub": (
        "Jakub Svoboda, 24 let, Brno (ochoten dojíždět/relokace Praha). "
        "Magisterské studium 'Datové inženýrství' na VUT FIT (2. ročník, "
        "dokončení 2026). Semestrální projekt: BI dashboard v Power BI "
        "pro studentský parlament (vizualizace rozpočtu, 4členný tým, "
        "vedoucí týmu). Půlroční stáž v analytickém týmu Komerční banky "
        "(reporting v SQL, čištění dat). Hard skills: SQL (pokročilý), "
        "Power BI, Python, Git, základy ETL. Soft skills: vedení týmu, "
        "prezentační dovednosti, analytické myšlení. Jazyky: čeština "
        "rodný, angličtina C1, němčina A2. Nejsilnější ze studentských "
        "profilů — má reálnou stáž v oboru."
    ),
    "tereza": (
        "Tereza Dvořáková, 23 let, Praha. Studuje bakaláře 'Informatika' "
        "na MUNI Brno (dokončila 2025, čerstvá absolventka). Freelance: "
        "tvorba Excel maker a jednoduchých reportů pro rodinnou firmu "
        "(fakturace, sklad). Erasmus semestr ve Vídni (mezikulturní "
        "komunikace). Hard skills: Excel (pokročilý, VBA makra), SQL "
        "základy, Tableau (samouk), základy Pythonu. Soft skills: "
        "samostatnost, adaptabilita, komunikace se zákazníkem. Jazyky: "
        "čeština rodný, angličtina B2, němčina B1. Slabší technické "
        "základy než Jakub, ale praktická zkušenost s reportingem."
    ),
}

_PROMPT = """\
Napiš realistické české CV pro následující profil studenta/čerstvého \
absolventa. Výstup je čistý text CV (žádné markdown nadpisy s #, žádné \
komentáře), strukturovaný do sekcí: Osobní údaje (jméno, e-mail, telefon, \
lokalita), Profesní shrnutí (2-3 věty), Vzdělání, Pracovní zkušenosti / \
brigády, Projekty, Hard skills, Soft skills, Jazyky. Délka 400-650 slov. \
Použij realistický český formát a tón. Vymysli plausibilní e-mail a \
telefon. Nepřeháněj zkušenosti — je to student.

PROFIL:
{brief}

CV (čistý text):"""


def _generate_cv(brief: str) -> str:
    """One LLM call → CV text. Uses the raw text endpoint, not JSON."""
    prompt = _PROMPT.replace("{brief}", brief)
    # The generator wants prose, not JSON — call the messages API directly.
    # Opus 4.8 removed `temperature`; variety across personas comes from their
    # distinct briefs, not a sampling knob.
    msg = llm._client().messages.create(
        model=llm.LLM_MODEL,
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(b.text for b in msg.content if getattr(b, "type", None) == "text").strip()


def main_for_test(*, force: bool = False, only: str | None = None) -> int:
    """Programmatic entry — usable from tests without argparse."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    personas = {only: PERSONAS[only]} if only and only in PERSONAS else PERSONAS

    written = 0
    for name, brief in personas.items():
        out_path = OUT_DIR / f"persona_{name}.txt"
        if out_path.exists() and not force:
            print(f"  skip {out_path} (exists; use --force to regenerate)")
            continue
        try:
            cv_text = _generate_cv(brief)
        except Exception as exc:  # noqa: BLE001
            print(f"  FAILED {name}: {exc}", file=sys.stderr)
            continue
        out_path.write_text(cv_text, encoding="utf-8")
        written += 1
        print(f"  wrote {out_path} ({len(cv_text)} chars)")

    print(f"Generated {written} student CV(s) in {OUT_DIR}.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate student CV samples.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Regenerate even if the output file already exists.",
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        help="Generate just one persona by name (anna / jakub / tereza).",
    )
    args = parser.parse_args()
    return main_for_test(force=args.force, only=args.only)


if __name__ == "__main__":
    sys.exit(main())
