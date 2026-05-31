# Deploy — Streamlit Community Cloud

## TL;DR
- Repo can stay **private** (Streamlit Cloud authorises GitHub for private repos).
- Main module: `src/cv_bau_students/ui/app.py`. `requirements.txt` already installs the
  package (the trailing `.`).
- Secrets carry the Anthropic key (and, for persistence, the Postgres URL).
- Default DB is **ephemeral SQLite** restored from the bundled `seed.sqlite.gz` on every
  cold start. For data that **survives restarts**, use an external Postgres (below).

## What lives where (privacy)
- `seed.sqlite.gz` (committed) holds **only open + synthetic data** — ESCO (CC BY 4.0),
  NSP/CDK (CC0), the scraped ad corpus, and the **synthetic** demo CVs (Apache-2.0). No
  real personal data is ever committed.
- Real uploaded CVs go into the **runtime DB**. On ephemeral SQLite they vanish on
  restart; on Postgres they persist in your private DB — never in GitHub.

## 1. Basic deploy (ephemeral SQLite)
1. [share.streamlit.io](https://share.streamlit.io) → **New app** → pick the repo +
   branch `main` + Main file `src/cv_bau_students/ui/app.py` → Deploy.
2. App **Settings → Secrets**:
   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."
   ```
   ⚠️ Every analysis runs on **your** key — anyone with the URL spends your credits. Set
   an Anthropic spend limit, or have users paste their own key.
3. To ship a **pre-populated** recruiter view, bake the demo into the seed first
   (locally, with the key):
   ```bash
   python -m scripts.seed_target_demo        # ad 341 + 6 synthetic candidates + matches
   python -m scripts.build_cloud_seed        # regenerates seed.sqlite.gz
   git commit + PR the new seed.sqlite.gz
   ```
   Otherwise the recruiter view is empty until someone uploads CVs (the scraped ad
   corpus is gitignored, so the target ad only exists via the seed).

## 2. Persistent deploy (Postgres) — uploaded CVs survive restarts
The schema is DB-agnostic (`config.DB_URL` reads `CV_BAU_STUDENTS_DB_URL`). Two extra
steps vs SQLite, because the seed-snapshot restore is SQLite-only:

1. **Provision** a free Postgres — [Neon](https://neon.tech) or
   [Supabase](https://supabase.com). Copy the connection URL
   (`postgresql://user:pass@host/db?sslmode=require`).
2. **Pour the data in once** (locally, after `seed_target_demo` so the SQLite holds the
   full demo):
   ```bash
   python -m scripts.migrate_sqlite_to_postgres --target "postgresql://...?sslmode=require"
   ```
   (`--truncate` to re-pour.) This copies ESCO/NSP taxonomy + ads + demo candidates into
   Postgres.
3. **Point the app at it** — Streamlit **Settings → Secrets**:
   ```toml
   ANTHROPIC_API_KEY      = "sk-ant-..."
   CV_BAU_STUDENTS_DB_URL = "postgresql://...?sslmode=require"
   ```
4. Redeploy. `ensure_seeded()` sees a populated DB (skills + ads) → no-op; the app now
   reads/writes Postgres. Uploaded CVs persist across restarts, in your private DB.

`requirements.txt` ships `psycopg2-binary`, so the Postgres driver is available on Cloud.

## Notes / gotchas (carried from cv-estimator)
- First launch is slow (plotly + Anthropic SDK cold import). `bootstrap.prewarm_llm()`
  warms the client in a daemon thread.
- A blank Streamlit first-run email prompt can stall the local window — put an empty
  `email = ""` in `~/.streamlit/credentials.toml`.
- Don't `rm data/cv_bau_students.sqlite` before a demo — the committed seed has 0 ads;
  the live DB holds the scraped corpus + target ad.
