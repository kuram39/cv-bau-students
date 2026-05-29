#!/usr/bin/env python3
"""CLI entry point for the meta-reflection pass.

Usage: python scripts/run_reflection.py [--batch-size N]
"""

import argparse
import json
import sys

from cv_bau_students.meta.reflect import reflect


def main() -> int:
    parser = argparse.ArgumentParser(description="Reflect on recent pipeline runs.")
    parser.add_argument("--batch-size", type=int, default=20)
    args = parser.parse_args()

    payload = reflect(batch_size=args.batch_size)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
