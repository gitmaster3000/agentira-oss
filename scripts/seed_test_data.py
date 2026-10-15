"""Seed the realistic PREVIEW dataset for staging and PR previews (AP-699).

    python scripts/seed_test_data.py            # idempotent: no-op if already seeded
    python scripts/seed_test_data.py --reset    # drop + reseed the preview org only

Creates one "Preview Org" with 4 projects (~600 / ~120 / ~60 / 4 tasks), long
markdown tasks, comments, commits, PR links, attachments, finished runs and
notifications. Writes straight to the DB — never wakes the daemon, calls an
LLM, GitHub, or any network. Other orgs are never touched.

    login →  preview / preview1234
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import sample_data  # noqa: E402
from backend.db import init_db  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--reset", action="store_true",
                    help="drop and reseed the preview org only")
    args = ap.parse_args()
    init_db()
    t0 = time.monotonic()
    res = sample_data.seed(reset=args.reset)
    if res["created"]:
        print(f"seeded preview org in {time.monotonic() - t0:.1f}s")
    else:
        print("preview org already seeded — nothing to do (use --reset to rebuild)")
    print(f"login →  {sample_data.PREVIEW_USER} / {sample_data.PREVIEW_PASSWORD}")


if __name__ == "__main__":
    main()
