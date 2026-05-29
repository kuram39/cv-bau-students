# Skill Taxonomy Sources — Evaluation for cv-bau-students

Goal: replace the 50-skill handcrafted mock with a real, structured, multilingual (CS/EN)
taxonomy of 500–5 000+ skills with canonical names, aliases, hierarchical relations, and
links to occupational families (CZ-ISCO / ISCO-08).

Verified May 2026. All claims sourced inline.

---

## TL;DR

- **Primary:** ESCO v1.2.1 (CC BY 4.0, 13 939 skills, 28 languages incl. Czech, full ISCO-08 mapping, CSV download). Score 5/5.
- **Secondary (Czech-specific reinforcement):** Czech NSP / CDK via `data.mpsv.cz` (open data, ~27 000 competencies, CZ-ISCO linked, JSON API). Score 4/5.
- **Tertiary (tech vocabulary booster):** Stack Overflow Tags dump (CC BY-SA 4.0). Score 3/5.
- **Skip:** Lightcast (API-only contracts), O*NET (US-centric SOC, no Czech), LinkedIn (partner-only), GitHub Topics (ToS friction, no structure).

Estimated effort to load ESCO into the SQLite schema: **8–12 hours** (download → parse 3 CSVs → normalize → insert). Detail in the final section.

---

## 1. ESCO — European Skills, Competences, Qualifications and Occupations

| Field | Value |
|---|---|
| URL | <https://esco.ec.europa.eu/en/use-esco/download> |
| License | CC BY 4.0 (Commission Decision 2011/833/EU on reuse) |
| Format | CSV, RDF, TTL, ODS, XML, JSON-LD; also REST API |
| Skill count | **13 939 skills** + 3 039 occupations (v1.2.1) |
| Hierarchy | Yes — 4 pillars (Knowledge / Language / Skills / Transversal), then `broaderRelationsSkillPillar.csv` recursively; `skillsHierarchy.csv` is the explicit tree |
| Aliases | Yes — `PREFERREDLABEL` + `ALTLABELS` columns per language; pipe-separated list of alternative labels |
| Czech | Yes — full translation; CSVs are mono-lingual, pick `skills_cs.csv` and `skills_en.csv` |
| ISCO mapping | Yes — ESCO occupations live at ISCO-08 level 5+; each occupation maps to exactly one ISCO-08 code. `occupationSkillRelations.csv` links skills↔occupations |
| Acquisition | Customize package on download portal → email verification → ZIP. Direct file: `https://esco.ec.europa.eu/sites/default/files/...` (latest stable v1.2.0 was May 2024, v1.2.1 patch 10/12/2025) |
| Suitability | **5/5** |

Sources: [Download portal](https://esco.ec.europa.eu/en/use-esco/download), [CSV format](https://esco.ec.europa.eu/en/about-esco/escopedia/escopedia/comma-separated-values-csv), [Dataset structure](https://esco.ec.europa.eu/en/structure-esco-downloadable-datasets), [Skills classification](https://esco.ec.europa.eu/en/classification/skill_main), [ISCO mapping](https://esco.ec.europa.eu/en/about-esco/escopedia/escopedia/international-standard-classification-occupations-isco).

Key CSV files we need:

- `skills_cs.csv` / `skills_en.csv` — `conceptUri`, `preferredLabel`, `altLabels`, `description`, `skillType`
- `broaderRelationsSkillPillar.csv` — `conceptUri` → `broaderUri` (parent edges)
- `occupationSkillRelations.csv` — `occupationUri` → `skillUri` + `relationType` (essential/optional)
- `ISCOGroups_cs.csv` — ISCO-08 group labels in Czech for the occupational-family bucket
- `occupations_cs.csv` — `iscoGroup` column links each occupation row to ISCO-08

---

## 2. O*NET — US Bureau of Labor

| Field | Value |
|---|---|
| URL | <https://www.onetcenter.org/database.html> |
| License | CC BY 4.0 |
| Format | XLSX, tab-delimited TXT, MySQL/Postgres/MSSQL/Oracle SQL |
| Skill count | 1 016 occupations; Essential Skills 17 880 rows; Transferable Skills 44 700 rows; Technology / Software Skills 31 821 rows |
| Hierarchy | Yes — Content Model: 41 generalized → 325 intermediate → 2 000+ detailed work activities → 19 000+ task statements |
| Aliases | Partial — "Sample of Reported Titles" file (7 953 rows) for occupations; skills themselves are flat |
| Czech | **No** — English only |
| ISCO mapping | **No** — uses O*NET-SOC (US Standard Occupational Classification). Crosswalks to ISCO exist but are external |
| Acquisition | <https://www.onetcenter.org/database.html?p=3> ZIP, ~50 MB |
| Suitability | **2/5** for a Czech pipeline (no Czech, no ISCO, US-occupation-centric) |

Sources: [O*NET DB](https://www.onetcenter.org/database.html), [License](https://www.onetonline.org/help/license).

Useful only as an English-side enrichment layer if you later want US-job comparability.

---

## 3. Lightcast (formerly Emsi Burning Glass) Open Skills

| Field | Value |
|---|---|
| URL | <https://lightcast.io/open-skills>, API docs <https://docs.lightcast.dev/apis/skills> |
| License | "Open" but **API-only, contract-based** since 2024; no bulk download |
| Format | REST API (JSON) |
| Skill count | ~34 000 skills, updated every 2 weeks |
| Hierarchy | Yes — categories + subcategories |
| Aliases | Yes — multiple per skill |
| Czech | No native Czech taxonomy; extraction in English. Multilingual extraction limited |
| ISCO mapping | No direct ISCO; their own occupation taxonomy |
| Acquisition | Register → API credentials (Client ID/Secret). Free tier exists for nonprofits/research; commercial use needs contract |
| Suitability | **2/5** — no bulk export, no Czech, contract risk |

Sources: [Open Skills FAQ](https://lightcast.io/open-skills/faqs), [Free API access](https://docs.lightcast.io/lightcast-api/docs/free-api-access), [Pricing notes](https://lightcast.io/open-skills/access).

Skip unless we need real-time tech-skill trending and can negotiate a contract.

---

## 4. Stack Overflow Tags

| Field | Value |
|---|---|
| URL | <https://archive.org/details/stackexchange> |
| License | CC BY-SA 4.0 (attribution + share-alike) |
| Format | 7z-compressed XML; `stackoverflow.com-Tags.7z` ~1.1 MB |
| Skill count | ~64 000 tags total on SO; ~5 000 are "active" tech skills. Older analyses cite ~23 000 unique tags |
| Hierarchy | **No** — flat tag list. Some informal parent tags (`tag-synonyms`) |
| Aliases | Partial — `tag-synonyms` table redirects e.g. `js` → `javascript` |
| Czech | No |
| ISCO mapping | No |
| Acquisition | Download from Internet Archive (last public dump: April 2024; public dumps paused due to SE/moderator dispute) |
| Suitability | **3/5** — great tech vocabulary boost, but flat, English-only, license requires SA on any redistributed derivative |

Sources: [SE Data Dump](https://archive.org/details/stackexchange), [April 2024 dump](https://academictorrents.com/details/5afacf7e3d23c75e19d7d94be7e83208a5e8423a), [State of dumps](https://search.feep.dev/blog/post/2025-02-20-state-of-stackexchange).

Useful as a tech-skill alias enrichment layer over ESCO ICT skills.

---

## 5. Czech NSP / CDK (Národní soustava povolání / Centrální databáze kompetencí)

| Field | Value |
|---|---|
| URL | Portal <https://nsp.cz/>, open data <https://data.mpsv.cz/web/data/narodni-soustava-povolani>, CDK <https://info.nsp.cz/>, API help <https://nsp.cz/napoveda/api> |
| License | Open Data per Act 435/2004 Coll. (Czech employment law); free reuse |
| Format | JSON via REST API (v1.0 / v1.1 / v1.2); bulk file exports also offered ("Soubory ke stažení") |
| Skill count | **>27 000 competencies** in CDK; categorized as digital (`/cdk/digi`), soft skills (`/cdk/soft-skill`), generic hard, specific hard |
| Hierarchy | Yes — competencies classified by content and type; explicit hierarchical organization in CDK |
| Aliases | Limited — `_legacySoftSkillCode_` field for back-compat; not a rich alias list like ESCO |
| Czech | **Native** — primary language is Czech |
| ISCO mapping | Yes — explicit CZ-ISCO linkage on every occupation; CZ-ISCO is a Czech extension of ISCO-08 |
| Acquisition | REST API with `Accept: application/json`, no auth required for public endpoints. Bulk dumps via MPSV open-data portal |
| Suitability | **4/5** for Czech reinforcement; **2/5** as a primary because the alias coverage is thinner than ESCO and there is no official multilingual side |

Sources: [NSP open data](https://data.mpsv.cz/web/data/narodni-soustava-povolani), [CDK](https://info.nsp.cz/), [API docs](https://nsp.cz/napoveda/api).

Best role: **secondary**. Reinforces ESCO with Czech-specific competencies and CZ-ISCO codes that ESCO's plain ISCO-08 lacks.

---

## 6. GitHub Topics

| Field | Value |
|---|---|
| URL | <https://github.com/topics> + REST API `/search/topics` |
| License | Mixed — content is user-generated; Topic *list* is not formally licensed for redistribution |
| Format | Web pages + REST API (JSON) |
| Skill count | ~10 000 curated topics; long tail of millions of free-form topics |
| Hierarchy | **No** — flat |
| Aliases | Topic aliases exist internally but not exposed |
| Czech | No |
| ISCO mapping | No |
| Acquisition | Public REST API (60 req/h unauth, 5 000 req/h with token). Per [GitHub AUP](https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies), scraping public non-personal data is permitted for research with open-access output; not permitted for spamming or selling user data |
| Suitability | **2/5** — flat, English, ToS friction for any commercial reuse |

Skip unless you specifically need a long-tail of emerging tech terms.

---

## 7. Other Sources Considered

| Source | Verdict |
|---|---|
| **LinkedIn Skills Graph** (~39 000 skills, 374 000 aliases, 26 locales) | Partner-only API; no public download. Skip. ([blog post](https://www.linkedin.com/blog/engineering/data/building-maintaining-the-skills-taxonomy-that-powers-linkedins-skills-graph)) |
| **Indeed Skills** | Not externally exposed |
| **Tabiya Inclusive Livelihoods Taxonomy** | ESCO-derived, adds informal-economy skills, CSV, MIT/CC. Worth a look if we extend to non-formal work. ([docs](https://docs.tabiya.org/our-tech-stack/inclusive-livelihoods-taxonomy/csv-format)) |
| **Eurostat ISCO-08 master** | Pure occupation codes, no skills. Already inside ESCO |
| **EU Skills Panorama** | Built on ESCO; no separate dataset |

---

## Ranking

| Rank | Source | Score | Role |
|---|---|---|---|
| 1 | **ESCO v1.2.1** | 5/5 | Primary spine — canonical skills, hierarchy, aliases, ISCO-08 mapping, Czech labels |
| 2 | **Czech NSP / CDK** | 4/5 | Secondary — CZ-ISCO codes, Czech-specific competencies, salary/vacancy linkage |
| 3 | **Stack Overflow Tags** | 3/5 | Tertiary — tech alias enrichment (`js` → `javascript`, `k8s` → `kubernetes`) |
| 4 | **O*NET 30.3** | 2/5 | Optional EN enrichment |
| 5 | **Lightcast Open Skills** | 2/5 | Skip (API-only, contract) |
| 6 | **GitHub Topics** | 2/5 | Skip |
| 7 | **LinkedIn Skills Graph** | 1/5 | Skip (no public access) |

---

## Recommendation

**Primary: ESCO v1.2.1.** It is the only source that ticks every box: open license (CC BY 4.0), structured CSV download, 13 939 skills with both preferred labels and rich `altLabels`, explicit broader/narrower hierarchy, native Czech translations, and a one-to-one mapping to ISCO-08 occupation groups. Single download, no auth, no API quota.

**Secondary: Czech NSP / CDK** via `data.mpsv.cz`. Layer on top of ESCO to: (a) translate ISCO-08 → CZ-ISCO codes that match Czech job-board taxonomies, (b) pick up Czech-only soft-skill phrasings that ESCO's translation may miss, and (c) inherit salary/vacancy data for downstream features.

**Optional enrichment: Stack Overflow `tag-synonyms`** to widen the `skill_aliases` table for ICT skills (cheap win, ~1 MB download).

---

## Mapping to Our SQLite Schema

Target schema (paraphrased from the prompt):

```sql
-- canonical_name, family, ...
CREATE TABLE skills (
  id INTEGER PRIMARY KEY,
  canonical_name TEXT NOT NULL,        -- ESCO preferredLabel (cs)
  canonical_name_en TEXT,              -- ESCO preferredLabel (en)
  family TEXT,                         -- ESCO pillar or ISCO major group
  esco_uri TEXT UNIQUE,                -- conceptUri
  skill_type TEXT                      -- knowledge | skill/competence | language | transversal
);

CREATE TABLE skill_aliases (
  alias TEXT NOT NULL,
  skill_id INTEGER REFERENCES skills(id),
  lang TEXT,                           -- 'cs' | 'en'
  source TEXT                          -- 'esco' | 'nsp' | 'so-synonyms'
);

CREATE TABLE skill_hierarchy (
  parent_id INTEGER REFERENCES skills(id),
  child_id INTEGER REFERENCES skills(id),
  PRIMARY KEY (parent_id, child_id)
);
```

Example load query (after staging ESCO CSVs into temp tables):

```sql
INSERT INTO skill_aliases (alias, skill_id, lang, source)
SELECT TRIM(value) AS alias, s.id, 'cs', 'esco'
FROM esco_skills_cs e
JOIN skills s ON s.esco_uri = e.conceptUri,
     json_each('["' || REPLACE(e.altLabels, '|', '","') || '"]')
WHERE TRIM(value) <> '';
```

---

## Effort Estimate — Loading ESCO into SQLite

| Step | Hours |
|---|---|
| Download v1.2.1 CS + EN CSV packages, verify checksums | 0.5 |
| Inspect schemas, document column drift vs docs | 1.0 |
| Write loader (Python + pandas or `sqlite3` `.import`) for `skills_cs.csv`, `skills_en.csv` | 2.0 |
| Parse `altLabels` (pipe-separated) into `skill_aliases` rows | 1.0 |
| Load `broaderRelationsSkillPillar.csv` into `skill_hierarchy` | 1.0 |
| Load `ISCOGroups_cs.csv` + `occupations_cs.csv`, derive `family` per skill via `occupationSkillRelations.csv` (use most-common ISCO major group) | 2.0 |
| Indexes (`idx_aliases_alias_lower`), unit tests, fixtures | 1.5 |
| Smoke test against a handful of real CVs | 1.0 |
| **Total** | **10 h** (range 8–12) |

Add **+3–5 h** to layer in NSP/CDK competencies (separate loader, dedupe against ESCO by Czech preferred label + fuzzy match on description).

Add **+1 h** to merge Stack Overflow `tag-synonyms.xml` as extra aliases for ESCO ICT-skill rows.

---

## Open Risks

- ESCO v1.2.1 is the latest stable as of Dec 2025; check for v1.3 before locking the loader.
- NSP API stability — v1.0 and v1.1 are still listed; pin to v1.2.
- CZ-ISCO ↔ ISCO-08 is mostly identical at the 4-digit level but diverges at 5-digit specializations; document the crosswalk we use.
- Stack Overflow CC BY-SA 4.0 is *share-alike* — if we redistribute the merged DB, the derivative must also be SA. ESCO (CC BY) and NSP (Czech open data) are compatible inbound but the SA clause taints outbound. Decision needed: keep SO data internal-only, or publish under CC BY-SA.
