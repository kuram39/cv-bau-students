# cv-bau-students

Student / fresh-graduate / career-changer matching pipeline. Extends a
BAU recruiter platform that already handles experienced candidates;
this repo provides the layer that handles CVs without years of work
history — school projects, thesis work, brigády, courses, and prior-
domain achievements get translated into "experienced-equivalent"
capabilities so the matcher can compare them against job ads written
for experienced candidates.

Sister project: [`cv-estimator`](https://github.com/buhlez31/cv-estimator)
(round-1 salary estimator). Shared infrastructure pattern (Pydantic
contract, LLM wrapper, skepticism prompt) but disjoint product scope.

## TL;DR

- **Pipeline.** Document extract → student / changer / experienced
  detector → profile extraction → iterative completion loop (asks for
  missing data) → capability translator (project / thesis / brigáda →
  experienced-language capabilities) → matcher (skill + bridge +
  personal fit) → reasoning.
- **Comparability stance.** Never compare years. Compare demonstrated
  skills + bridgeable gaps to next level. Per-domain junior / medior /
  senior checklists encode what's bridgeable in a short course versus
  what can't be shortcut.
- **Data layer.** SQLite from day one via SQLAlchemy — 10 relational
  tables for candidates, taxonomy, level checklists, job ads, matches,
  reasoning cache. CSV files are the human-edited source of truth,
  loaded into the DB on startup.
- **Cost discipline.** Tables / Python for everything deterministic
  (taxonomy, alias resolution, bridge math, hard filters). LLM only
  for unstructured-text passes: profile extraction, completion
  questions, capability translation, reasoning.

## Run (local dev)

```bash
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements-dev.txt
pip install -e . --no-deps     # editable install for development

cp .env.example .env           # add ANTHROPIC_API_KEY

# Build the SQLite database + load taxonomy + level checklists
python scripts/load_seeds.py

pytest -q                      # 5+ tests, in-memory SQLite, no network

# Streamlit UI lands in Phase 7
# streamlit run src/cv_bau_students/ui/app.py
```

## Status

- [x] Phase 1 — repo + SQLite schema + tests + loader
- [ ] Phase 2 — student / changer detector + profile extraction
- [ ] Phase 3 — iterative completion loop
- [ ] Phase 4 — capability translator
- [ ] Phase 5 — job-ad corpus + taxonomy + level checklists loaded
- [ ] Phase 6 — matcher + scoring via SQL
- [ ] Phase 7 — reasoning + recruiter UX
- [ ] Phase 8 — career-changer parity
- [ ] Phase 8.5 — meta-reflection log
- [ ] Phase 9 — README + diagrams (refresh)

See `~/.claude/plans/1-chybi-ve-vyslednych-imperative-wave.md` for the
full phase breakdown and design rationale.

## Layout

```
src/cv_bau_students/
├── config.py              # paths, weights, DB URL
├── db.py                  # SQLAlchemy session factory
├── db_models.py           # 10-table ORM schema
├── models.py              # Pydantic pipeline contract
├── llm.py                 # Anthropic wrapper (mirrors cv-estimator)
├── extractors/            # document.py + (Phase 2) profile.py
├── detector/              # (Phase 2) student / changer classifier
├── completion/            # (Phase 3) iterative missing-data loop
├── translator/            # (Phase 4) capability translation
├── jobads/                # (Phase 5) job-ad ingest + normalise
├── taxonomy/              # (Phase 5) skill taxonomy repository
├── levels/                # (Phase 6) bridge_plan + level checklist
├── matcher/               # (Phase 6) hard filter + 3-axis scoring
├── explanation/           # (Phase 7) reasoning LLM
├── meta/                  # (Phase 8.5) reflection log generator
├── validation/            # output-range invariants
├── prompts/               # *.md prompt artefacts (Phase 2+)
├── data/                  # human-edited CSV seeds + SQLite runtime
└── ui/                    # Streamlit recruiter view (Phase 7)
scripts/                   # CLI entry points
tests/                     # pytest suite (in-memory SQLite)
```

## License

MIT — see [LICENSE](LICENSE).
