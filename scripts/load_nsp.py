#!/usr/bin/env python3
"""Layer Czech NSP / CDK competencies on top of the ESCO base.

NSP (Národní soustava povolání) + CDK (Centrální databáze kompetencí)
publish Czech-native phrasings + CZ-ISCO occupation codes via the
data.mpsv.cz open-data portal. We use them as a *secondary* source —
they enrich rather than replace ESCO entries:

  * If an NSP competency matches an existing ESCO skill (by name or
    aliased name), attach its NSP code + any extra Czech aliases.
  * If an NSP competency has no ESCO match, insert as a stand-alone
    `Skill` row with `source="nsp"` on its aliases.

Run AFTER `scripts/load_esco.py`. Idempotent: re-running upserts.

Usage:
    python scripts/load_nsp.py --source data/raw_nsp/competencies.json
    python scripts/load_nsp.py --api                       # pull live

Live API (CDK — Centrální databáze kompetencí, no auth, public):
    https://nsp.cz/api/v1.2/cdk/soft-skill   # měkké (transversal) kompetence
    https://nsp.cz/api/v1.2/cdk/digi         # digitální kompetence
Each returns ``{"code":200,"data":[{...}]}``; we fetch the full list in one
request (these two endpoints are not paginated). The hard-skill catalogue lives
at ``/api/v1.2/cdk/competence`` but is offset-paginated over ~10k rows with a
numeric ``type`` taxonomy — left for a follow-up (see ``_fetch_from_api``).

NOTE: the CDK competency lists carry NO CZ-ISCO occupation codes — linking
competencies to CZ-ISCO via NSP work-units is a separate follow-up; we persist
``cz_isco=[]`` here.

License: CC0 (data.mpsv.cz / NSP open data terms).
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

from sqlalchemy import select, update

from cv_bau_students.db import get_session, init_db
from cv_bau_students.db_models import Skill, SkillAlias
from cv_bau_students.taxonomy.repo import resolve_skill


def _load_local(path: Path) -> list[dict]:
    """Load an NSP competency dump from disk.

    Expected shape (per data.mpsv.cz CSV → JSON export):
        [
          {
            "kod": "k123",
            "nazev": "Programování v jazyce Python",
            "synonyma": ["Python programming", "vývoj v Pythonu"],
            "typ": "odborná dovednost",
            "cz_isco": ["25120", "25121"]
          },
          ...
        ]
    """
    if not path.exists():
        print(f"NSP source not found: {path}", file=sys.stderr)
        sys.exit(2)
    return json.loads(path.read_text(encoding="utf-8"))


# Live CDK endpoints (no auth; Accept: application/json). Both return the full
# list in a single response — unlike /cdk/competence (hard skills), which is
# offset-paginated over ~10k rows and left for a follow-up.
_API_BASE = "https://nsp.cz/api/v1.2/cdk"
_API_TIMEOUT = 20  # seconds — never hang


def _fetch_list(endpoint: str) -> list[dict]:
    """GET ``{_API_BASE}/{endpoint}`` and return the ``data`` list.

    Uses only the stdlib (urllib) — no new dependency. Raises on any
    transport/parse error; the caller turns that into a clean non-zero exit.
    """
    url = f"{_API_BASE}/{endpoint}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=_API_TIMEOUT) as resp:  # noqa: S310
        payload = json.loads(resp.read().decode("utf-8"))
    data = payload.get("data")
    if not isinstance(data, list):
        raise ValueError(f"unexpected CDK response shape from {url}: missing 'data' list")
    return data


def _fetch_from_api() -> list[dict]:
    """Pull live CDK soft-skill + digi competencies and normalise to the
    ``_persist_competency`` dict shape.

    Mapping (CDK item -> competency dict):
      * nazev    = title
      * synonyma = [title]  the only reliable Czech phrasing the CDK lists give.
                   We register it as an explicit cs/nsp alias so the title is
                   reachable through the alias index, not just canonical_name.
                   The CDK lists expose no other synonym-like field
                   (``legacySoftSkillCode`` is an opaque code like "a04", not a
                   human alias), so we add nothing else.
      * typ      = a Czech type string _map_type understands:
                     soft-skill -> "měkká kompetence" -> "transversal"
                     digi       -> "odborná digitální dovednost" -> "skill"
      * kod      = code  (CDK competency code, e.g. "1.1")
      * cz_isco  = []  (CDK lists carry no ISCO; CZ-ISCO join is a follow-up)
    """
    comps: list[dict] = []

    for item in _fetch_list("soft-skill"):
        title = (item.get("title") or "").strip()
        if not title:
            continue
        comps.append(
            {
                "kod": (item.get("code") or "").strip(),
                "nazev": title,
                "synonyma": [title],
                "typ": "měkká kompetence",
                "cz_isco": [],
            }
        )

    for item in _fetch_list("digi"):
        title = (item.get("title") or "").strip()
        if not title:
            continue
        comps.append(
            {
                "kod": (item.get("code") or "").strip(),
                "nazev": title,
                "synonyma": [title],
                "typ": "odborná digitální dovednost",
                "cz_isco": [],
            }
        )

    return comps


def _persist_competency(comp: dict) -> tuple[int, int]:
    """Returns (skills_touched, aliases_added)."""
    code = (comp.get("kod") or "").strip()
    name = (comp.get("nazev") or "").strip()
    if not name:
        return 0, 0
    synonyms = [s.strip() for s in comp.get("synonyma", []) if s.strip()]
    nsp_type = (comp.get("typ") or "skill").strip()

    # 1. Try to attach to existing skill (ESCO match).
    match = resolve_skill(name)
    aliases_added = 0
    with get_session() as session:
        if match is not None:
            skill_id, _ = match
            if code:
                session.execute(update(Skill).where(Skill.id == skill_id).values(nsp_code=code))
        else:
            # Insert stand-alone (no ESCO equivalent).
            existing = session.execute(
                select(Skill).where(Skill.canonical_name == name)
            ).scalar_one_or_none()
            if existing is None:
                row = Skill(
                    canonical_name=name,
                    nsp_code=code or None,
                    skill_type=_map_type(nsp_type),
                )
                session.add(row)
                session.flush()
                skill_id = row.id
            else:
                skill_id = existing.id
                if code:
                    session.execute(update(Skill).where(Skill.id == skill_id).values(nsp_code=code))

        # 2. Synonyms as CS aliases.
        for syn in synonyms:
            alias_lower = syn.lower().strip()
            if not alias_lower:
                continue
            exists = session.execute(
                select(SkillAlias.id).where(
                    SkillAlias.alias == alias_lower,
                    SkillAlias.lang == "cs",
                    SkillAlias.source == "nsp",
                )
            ).scalar_one_or_none()
            if exists:
                continue
            session.add(
                SkillAlias(
                    alias=alias_lower,
                    canonical_id=skill_id,
                    lang="cs",
                    source="nsp",
                )
            )
            aliases_added += 1
    return 1, aliases_added


def _map_type(nsp_type: str) -> str:
    t = nsp_type.lower()
    if "odborná" in t or "technická" in t:
        return "skill"
    if "měkká" in t or "mekka" in t or "osobnost" in t:
        return "transversal"
    if "jazyk" in t:
        return "language"
    return "skill"


def main_args(*, source: Path | None = None, api: bool = False, verbose: bool = True) -> int:
    """Programmatic entry point — usable from tests."""
    init_db()

    if api:
        try:
            competencies = _fetch_from_api()
        except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
            print(f"NSP CDK live fetch failed: {exc}", file=sys.stderr)
            return 1
    elif source is None:
        print("No --source given and --api not set.", file=sys.stderr)
        return 2
    else:
        competencies = _load_local(source)

    touched = 0
    aliases = 0
    for comp in competencies:
        t, a = _persist_competency(comp)
        touched += t
        aliases += a

    if verbose:
        print(f"Touched {touched} skills, added {aliases} NSP aliases.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Load NSP / CDK competencies.")
    parser.add_argument(
        "--source",
        type=Path,
        default=Path("data/raw_nsp/competencies.json"),
        help="Path to a pre-downloaded NSP competency JSON dump.",
    )
    parser.add_argument(
        "--api",
        action="store_true",
        help="Pull live from data.mpsv.cz instead of local file. TODO: wire endpoint.",
    )
    args = parser.parse_args()
    return main_args(source=args.source, api=args.api)


if __name__ == "__main__":
    sys.exit(main())
