#!/usr/bin/env python3
"""Checks on the generated reading list.

The reading list is fetched automatically, but the editorial notes on the
curated papers are written by hand. That boundary is the whole point of
the page, and it is exactly the kind of thing that erodes quietly: a
refactor drops a field, the feed still renders, and the curated shelf
silently degrades into the fetched abstracts it was meant to improve on.

So this asserts the boundary rather than trusting it:

  - every curated paper carries both editorial notes, non-trivially
  - no automatically selected paper carries them
  - required metadata is present, and no paper is listed twice

Standard library only:

    python scripts/check_reading.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEED = ROOT / "reading" / "papers.json"

NOTE_FIELDS = ("establishes", "unsettled")
REQUIRED = ("id", "title", "authors", "summary", "published", "url")
MIN_NOTE_CHARS = 40


def main() -> int:
    if not FEED.exists():
        print(f"FAIL {FEED.relative_to(ROOT).as_posix()} is missing")
        return 1

    data = json.loads(FEED.read_text(encoding="utf-8"))
    failures = 0
    curated_count = 0
    recent_count = 0
    seen: dict[str, str] = {}

    tracks = data.get("tracks") or []
    if not tracks:
        print("FAIL feed contains no tracks - refusing to pass vacuously")
        return 1

    for track in tracks:
        tid = track.get("id", "?")

        for paper in track.get("curated", []):
            curated_count += 1
            pid = paper.get("id", "?")
            label = f"{tid}/curated/{pid}"

            for field in REQUIRED:
                if not paper.get(field):
                    print(f"FAIL {label}: missing {field}")
                    failures += 1

            for field in NOTE_FIELDS:
                note = (paper.get(field) or "").strip()
                if not note:
                    print(f"FAIL {label}: curated paper has no {field!r} note")
                    failures += 1
                elif len(note) < MIN_NOTE_CHARS:
                    print(
                        f"FAIL {label}: {field!r} note is {len(note)} chars, "
                        f"too short to be a real assessment"
                    )
                    failures += 1

            if pid in seen:
                print(f"FAIL {label}: already listed in {seen[pid]}")
                failures += 1
            else:
                seen[pid] = label

        for paper in track.get("recent", []):
            recent_count += 1
            pid = paper.get("id", "?")
            label = f"{tid}/recent/{pid}"

            for field in REQUIRED:
                if not paper.get(field):
                    print(f"FAIL {label}: missing {field}")
                    failures += 1

            for field in NOTE_FIELDS:
                if (paper.get(field) or "").strip():
                    print(
                        f"FAIL {label}: automatically selected paper carries "
                        f"a {field!r} note; only curated papers are annotated"
                    )
                    failures += 1

    if curated_count == 0:
        print("FAIL no curated papers found - refusing to pass vacuously")
        failures += 1

    print(
        f"\n{len(tracks)} tracks, {curated_count} curated "
        f"(annotated), {recent_count} automatically selected"
    )
    if failures:
        print(f"{failures} problem(s) found")
        return 1
    print("no problems found")
    return 0


if __name__ == "__main__":
    sys.exit(main())
