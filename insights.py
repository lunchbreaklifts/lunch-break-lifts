#!/usr/bin/env python3
"""
Pull performance stats for every published post and save them to stats.csv.
Run weekly (before new posts are written) so the generator can learn what works.

Needs IG_ACCESS_TOKEN with the instagram_business_manage_insights permission.
If anything goes wrong it prints a note and exits cleanly, so it never blocks
the weekly content run.

Usage:
    python insights.py
"""

import csv
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from common import CONFIG, ROOT, load_posts

API = f"https://graph.instagram.com/{CONFIG.get('instagram_api_version', 'v23.0')}"
TZ = ZoneInfo(CONFIG.get("timezone", "America/Denver"))
STATS_CSV = ROOT / "stats.csv"
METRICS = ["reach", "views", "likes", "comments", "shares", "saved"]
STAT_FIELDS = ["id", "media_id", "format", "hook", "published_at", "checked_at"] + METRICS + ["score"]


def score(row):
    """Saves and shares matter most for growth, then comments, then likes."""
    n = lambda k: int(row.get(k) or 0)
    return n("saved") * 4 + n("shares") * 4 + n("comments") * 2 + n("likes")


def fetch(media_id, token):
    """Get metrics for one post. Asks for all at once, then one by one if that's rejected."""
    def ask(metrics):
        r = requests.get(f"{API}/{media_id}/insights",
                         params={"metric": ",".join(metrics), "access_token": token}, timeout=60)
        data = r.json()
        if "error" in data:
            raise RuntimeError(data["error"].get("message", "unknown error"))
        out = {}
        for item in data.get("data", []):
            vals = item.get("values") or [{}]
            out[item["name"]] = vals[0].get("value", item.get("total_value", {}).get("value", 0))
        return out

    try:
        return ask(METRICS)
    except RuntimeError as first_error:
        out = {}
        for m in METRICS:
            try:
                out.update(ask([m]))
            except RuntimeError:
                pass
        if not out:
            raise first_error
        return out


def load_stats():
    if not STATS_CSV.exists():
        return {}
    with STATS_CSV.open(encoding="utf-8-sig", newline="") as f:
        return {r["id"]: r for r in csv.DictReader(f)}


def save_stats(stats):
    with STATS_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=STAT_FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in sorted(stats.values(), key=lambda r: r.get("published_at", "")):
            w.writerow(r)


def main():
    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if not token:
        print("No IG_ACCESS_TOKEN set; skipping stats.")
        return

    posts = [p for p in load_posts() if p["status"].lower() == "published" and p["media_id"]]
    if not posts:
        print("No published posts yet; nothing to measure.")
        return

    stats = load_stats()
    now = datetime.now(TZ).isoformat(timespec="seconds")
    updated = 0
    for p in posts:
        try:
            m = fetch(p["media_id"], token)
        except (RuntimeError, requests.RequestException, ValueError) as e:
            print(f"  couldn't get stats for [{p['id']}]: {e}")
            continue
        row = {"id": p["id"], "media_id": p["media_id"], "format": p.get("format", ""),
               "hook": p["hook"], "published_at": p["published_at"], "checked_at": now}
        row.update({k: m.get(k, 0) for k in METRICS})
        row["score"] = score(row)
        stats[p["id"]] = row
        updated += 1
        print(f"  [{p['id']}] reach {row['reach']}, saves {row['saved']}, shares {row['shares']} -> score {row['score']}")

    if updated:
        save_stats(stats)
    print(f"Updated stats for {updated} of {len(posts)} published posts.")


def performance_notes(min_posts=4, age_days=2):
    """Short summary for the post generator: what did best and worst so far."""
    stats = list(load_stats().values())
    now = datetime.now(TZ)
    ripe = []
    for r in stats:
        try:
            if (now - datetime.fromisoformat(r["published_at"]).astimezone(TZ)).days >= age_days:
                ripe.append(r)
        except (KeyError, ValueError):
            continue
    if len(ripe) < min_posts:
        return ""
    ripe.sort(key=lambda r: int(r.get("score") or 0), reverse=True)
    k = min(3, len(ripe) // 2)

    def line(r):
        fmt = f", {r['format']}" if r.get("format") else ""
        return (f'- "{r["hook"]}" (reach {r.get("reach", 0)}, saves {r.get("saved", 0)}, '
                f'shares {r.get("shares", 0)}{fmt})')

    best = "\n".join(line(r) for r in ripe[:k])
    worst = "\n".join(line(r) for r in ripe[-k:])
    return f"""

What's working on this page so far (real numbers from Instagram):
Best performers:
{best}
Weakest performers:
{worst}
Write more posts like the best ones (similar topics, hook styles, and formats) and fewer like
the weakest. Don't copy the best hooks; find new angles in the same spirit."""


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never block the weekly run
        print(f"Stats step hit a problem and was skipped: {e}")
        sys.exit(0)
