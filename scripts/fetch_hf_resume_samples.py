#!/usr/bin/env python3
"""Fetch experienced-track CV samples from a public HuggingFace dataset.

Source: InferencePrince555/Resume-Dataset (Apache 2.0). We pull via the
public HF datasets-server REST API (no `datasets` library dependency —
keeps the venv light and dodges the heavy pyarrow install).

The dataset stores resume bodies in a `Resume_test` column and the job
category in `instruction` ("Generate a Resume for a Data Science Job").
We filter to data-analyst-adjacent categories, pick the N longest
bodies (proxy for richness), append a Czech-context anchor block so the
matcher's language + location hard-filter passes our CZ ad, and write
each to `data/raw_cv_samples/experienced/hf_sample_{i}.txt`.

Fallback: if the HF endpoint is unreachable, copy the in-repo
hand-curated fixtures from `tests/fixtures/experienced_fallback/`.

Usage:
    python -m scripts.fetch_hf_resume_samples
    python -m scripts.fetch_hf_resume_samples --count 3 --category "Data Science"

License attribution: see NOTICES.md.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.parse
from pathlib import Path

HF_FILTER_URL = "https://datasets-server.huggingface.co/filter"
HF_DATASET = "InferencePrince555/Resume-Dataset"

# Categories to try, in order. The dataset uses these exact instruction
# strings. Data-analyst-adjacent first, broader IT as backstop.
CANDIDATE_CATEGORIES = [
    "Data Science",
    "Information Technology",
    "Business Development",
]

OUT_DIR = Path("data/raw_cv_samples/experienced")
FALLBACK_DIR = Path("tests/fixtures/experienced_fallback")

# Appended to every HF sample so the CZ matcher hard-filter (location +
# language KO) doesn't drop these EN-only resumes. The body stays English
# (it's what the extractor LLM reads); only this anchor is Czech.
CZ_ANCHOR = (
    "\n\n--- Doplňující údaje (lokalizace pro CZ trh) ---\n"
    "Lokalita: Praha\n"
    "Jazyky: čeština (rodný, C2), angličtina (C1)\n"
)

REQUEST_TIMEOUT_S = 60


def _http_get_json(url: str) -> dict:
    """GET JSON via `curl` subprocess.

    Python's urllib SSL path is unreliable in this environment (the same
    cert issue that blocks `pip install -e .`), but the system `curl`
    works. Shell out to it.
    """
    result = subprocess.run(
        ["curl", "-s", "--max-time", str(REQUEST_TIMEOUT_S), url],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def _fetch_category(category: str, *, want: int) -> list[str]:
    """Return up to `want` resume bodies for a given instruction category."""
    where = urllib.parse.quote(f"\"instruction\" LIKE '%{category}%'")
    # Pull a generous window so we can pick the longest bodies.
    url = (
        f"{HF_FILTER_URL}?dataset={urllib.parse.quote(HF_DATASET)}"
        f"&config=default&split=train&where={where}&offset=0&length=100"
    )
    payload = _http_get_json(url)

    bodies: list[str] = []
    seen: set[str] = set()
    for r in payload.get("rows", []):
        body = (r.get("row", {}) or {}).get("Resume_test")
        if not body or not isinstance(body, str) or len(body) < 400:
            continue
        body = body.strip()
        # Dedup — the dataset contains many near-identical copies. Key on
        # a normalised prefix so trivially different whitespace collapses.
        key = " ".join(body[:300].split()).lower()
        if key in seen:
            continue
        seen.add(key)
        bodies.append(body)
    # Longest first — richer profiles make a better demo.
    bodies.sort(key=len, reverse=True)
    return bodies[:want]


def _write_samples(bodies: list[str]) -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    for i, body in enumerate(bodies, start=1):
        path = OUT_DIR / f"hf_sample_{i}.txt"
        path.write_text(body + CZ_ANCHOR, encoding="utf-8")
        written += 1
        print(f"  wrote {path} ({len(body)} chars + CZ anchor)")
    return written


def _use_fallback(count: int) -> int:
    """Copy in-repo hand-curated fixtures when HF is unreachable."""
    if not FALLBACK_DIR.exists():
        print(
            f"HF unreachable AND no fallback dir at {FALLBACK_DIR}. "
            f"Cannot source experienced CVs.",
            file=sys.stderr,
        )
        return 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    written = 0
    for i, src in enumerate(sorted(FALLBACK_DIR.glob("*.txt"))[:count], start=1):
        dest = OUT_DIR / f"hf_sample_{i}.txt"
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        written += 1
        print(f"  fallback: {src.name} -> {dest}")
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch HF resume samples.")
    parser.add_argument("--count", type=int, default=3, help="How many CVs to fetch.")
    parser.add_argument(
        "--category",
        type=str,
        default=None,
        help="Override the instruction category filter (e.g. 'Data Science').",
    )
    parser.add_argument(
        "--force-fallback",
        action="store_true",
        help="Skip HF, use in-repo fixtures (offline demo).",
    )
    args = parser.parse_args()

    if args.force_fallback:
        n = _use_fallback(args.count)
        print(f"Wrote {n} experienced CV(s) from fallback fixtures.")
        return 0 if n else 1

    categories = [args.category] if args.category else CANDIDATE_CATEGORIES
    collected: list[str] = []
    for cat in categories:
        if len(collected) >= args.count:
            break
        try:
            bodies = _fetch_category(cat, want=args.count - len(collected))
            if bodies:
                print(f"  category '{cat}': {len(bodies)} usable resumes")
                collected.extend(bodies)
        except (subprocess.CalledProcessError, json.JSONDecodeError, OSError) as exc:
            print(f"  HF fetch failed for '{cat}': {exc}", file=sys.stderr)

    if not collected:
        print("HF returned nothing — falling back to in-repo fixtures.", file=sys.stderr)
        n = _use_fallback(args.count)
        return 0 if n else 1

    written = _write_samples(collected[: args.count])
    print(f"Wrote {written} experienced CV(s) to {OUT_DIR}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
