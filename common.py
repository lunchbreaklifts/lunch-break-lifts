"""Shared config and posts.csv helpers used by every script."""

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
POSTS_CSV = ROOT / "posts.csv"
OUTPUT = ROOT / "output"
FIELDS = ["id", "created", "status", "hook", "slides", "caption", "hashtags", "published_at", "media_id", "format", "audio", "facebook_id"]
SLIDE_SEP = " || "

# Status flow: draft -> approved -> rendered -> published
#   draft     = waiting for your review (only when auto_approve is false)
#   approved  = will be rendered into slides
#   rendered  = slides ready, waiting in the posting queue
#   published = live on Instagram


def load_posts():
    if not POSTS_CSV.exists():
        return []
    with POSTS_CSV.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        for field in FIELDS:
            row[field] = (row.get(field) or "").strip()
    return rows


def save_posts(rows):
    try:
        with POSTS_CSV.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    except PermissionError:
        sys.exit("posts.csv is locked. Close it in Excel and run again.")


def split_slides(text):
    return [s.strip() for s in text.split("||") if s.strip()]
