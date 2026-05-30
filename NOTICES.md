# Third-party Data Notices

This project's source code is licensed under MIT (see `LICENSE`). The
bundled taxonomy data shipped in `src/cv_bau_students/data/` and used
at runtime is **not** MIT-licensed — it is governed by the licenses of
its respective sources, as listed below.

---

## ESCO v1.2.x — European Skills, Competences, Qualifications and Occupations

- **Source:** European Commission — <https://esco.ec.europa.eu>
- **License:** Creative Commons Attribution 4.0 International (CC BY 4.0) —
  <https://creativecommons.org/licenses/by/4.0/>
- **Required attribution (per ESCO terms):**
  > *"This service uses the ESCO classification of the European Commission."*
- **Files derived from ESCO in this repository:**
  - `src/cv_bau_students/data/seed.sqlite.gz` — gzipped SQLite snapshot
    containing all ESCO skills, skillGroups, hierarchy edges, and
    occupation→skill mapping. Rebuilt from raw CSVs via
    `scripts/build_cloud_seed.py`.
  - `src/cv_bau_students/data/esco_skills.csv` and
    `src/cv_bau_students/data/esco_aliases.csv` — legacy CSV export
    (slow Cloud-fallback path, kept for compatibility).
- **Raw download:** `data/raw_esco/` (gitignored) holds the official
  ESCO v1.2.1 CSV bundle. Download from
  <https://esco.ec.europa.eu/en/use-esco/download> (email-gated form).
- **Modifications:** ESCO concepts are loaded into a relational schema
  (`Skill`, `SkillAlias`, `SkillHierarchy`, `SkillIndustryMap`) with
  preferredLabel/altLabel split into separate rows. No content is
  altered; only structural reshape.

## Czech NSP / CDK — Národní soustava povolání / Centrální databáze kompetencí

- **Source:** Ministerstvo práce a sociálních věcí ČR — <https://data.mpsv.cz>
- **License:** CC0 (public domain dedication)
- **Files derived from NSP in this repository:**
  - `data/raw_nsp/competencies_seed.json` — small demo set of CDK
    competency entries (CZ name, synonyms, CZ-ISCO codes).
  - NSP rows are also folded into `seed.sqlite.gz` when present at
    build time.
- **Modifications:** NSP competencies are matched against ESCO
  preferred labels; on match the NSP code is stitched onto the existing
  ESCO row. On no match the NSP row is inserted as a stand-alone skill.

---

## Job-ad text

- **Source:** Owner's pre-existing Apify scrape of public Jobs.cz
  listings, gitignored under `data/raw_ads/scraped/`.
- **Status:** Used as structural priors for the matcher — no scraped
  text is committed. The normalised JSON at `data/raw_ads/normalised.json`
  is committed and contains only required-fields schema (title, level,
  domain, location, must-have / nice-to-have skill arrays).
