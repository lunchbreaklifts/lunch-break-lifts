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
import json
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
WATCH = "ig_reels_avg_watch_time"  # Reels only, in milliseconds
STAT_FIELDS = (["id", "media_id", "format", "style", "hook", "published_at", "checked_at"] + METRICS
               + ["avg_watch_s", "score"])


def real_comments(row):
    """Comments minus the robot's own first comment on each post."""
    n = int(row.get("comments") or 0)
    return max(0, n - 1) if CONFIG.get("first_comment", True) else n


def score(row):
    """Saves and shares matter most for growth, then real comments, then watch time (every
    second people stay = 2 points), then likes. Views count a little (every 20 = 1 point)."""
    n = lambda k: int(row.get(k) or 0)
    watch = float(row.get("avg_watch_s") or 0)
    return (n("saved") * 4 + n("shares") * 4 + real_comments(row) * 3 + round(watch * 2)
            + n("likes") + n("views") // 20)


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
        return ask(METRICS + [WATCH])
    except RuntimeError:
        pass
    try:
        return ask(METRICS)
    except RuntimeError as first_error:
        out = {}
        for m in METRICS + [WATCH]:
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
               "style": p.get("style", ""), "hook": p["hook"], "published_at": p["published_at"],
               "checked_at": now}
        row.update({k: m.get(k, 0) for k in METRICS})
        if m.get(WATCH):
            row["avg_watch_s"] = round(float(m[WATCH]) / 1000, 1)
        row["score"] = score(row)
        stats[p["id"]] = row
        updated += 1
        watch = f", watched {row['avg_watch_s']}s" if row.get("avg_watch_s") else ""
        print(f"  [{p['id']}] reach {row['reach']}, saves {row['saved']}, shares {row['shares']}{watch} -> score {row['score']}")

    if updated:
        save_stats(stats)
    print(f"Updated stats for {updated} of {len(posts)} published posts.")
    try:
        update_best_times(token)
    except Exception as e:
        print(f"  best posting times not updated: {e}")


BEST_TIMES = ROOT / "best_times.json"
# Meta reports follower activity by hour in Pacific time (same as its other insights).
ACTIVITY_TZ = ZoneInfo("America/Los_Angeles")
WINDOWS = {"lunch": range(10, 14), "evening": range(16, 21)}  # local hours we're willing to post in


def update_best_times(token):
    """Once the account has 100+ followers, Instagram reports when followers are online.
    Pick the busiest lunch hour and evening hour (Denver time) and save them for the posting job."""
    r = requests.get(f"{API}/me/insights", timeout=60,
                     params={"metric": "online_followers", "period": "lifetime", "access_token": token}).json()
    if "error" in r:
        print(f"  follower activity not available yet ({r['error'].get('message', '')[:80]})")
        return
    try:
        by_hour = r["data"][0]["values"][-1]["value"]
    except (KeyError, IndexError, TypeError):
        print("  follower activity not available yet (needs 100+ followers)")
        return
    if not by_hour or sum(by_hour.values()) == 0:
        return
    local = {}
    today = datetime.now(ACTIVITY_TZ).replace(minute=0, second=0, microsecond=0)
    for h, n in by_hour.items():
        t = today.replace(hour=int(h)).astimezone(TZ)
        local[t.hour] = local.get(t.hour, 0) + int(n)
    slots = []
    for name, hours in WINDOWS.items():
        best = max(hours, key=lambda h: local.get(h, 0))
        slots.append(f"{best:02d}:00")
    BEST_TIMES.write_text(json.dumps({"slots": slots, "updated": datetime.now(TZ).isoformat(timespec="seconds"),
                                      "followers_online_by_hour": local}, indent=1), encoding="utf-8")
    print(f"  best posting times (Denver): {', '.join(slots)}")


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
    reels = [r for r in ripe if "reel" in (r.get("format") or "")]
    if len(reels) >= min_posts:  # every post is a Reel now, so compare like with like
        ripe = reels
    if len(ripe) < min_posts:
        return ""
    for r in ripe:
        r["score"] = score(r)  # re-score older rows with the current formula
    ripe.sort(key=lambda r: int(r.get("score") or 0), reverse=True)
    k = min(3, len(ripe) // 2)

    def line(r):
        kind = r.get("style") or r.get("format") or ""
        watch = f"watched {r['avg_watch_s']}s, " if r.get("avg_watch_s") else ""
        return (f'- "{r["hook"]}" ({kind}: {watch}views {r.get("views", 0)}, real comments '
                f'{real_comments(r)}, saves {r.get("saved", 0)}, shares {r.get("shares", 0)})')

    best = "\n".join(line(r) for r in ripe[:k])
    worst = "\n".join(line(r) for r in ripe[-k:])
    return f"""

What's working on this page so far (real numbers from Instagram):
Best performers:
{best}
Weakest performers:
{worst}
Watch time is the main signal at this stage: it's how long people stay before scrolling.
Write more posts like the best ones (similar topics, hook styles, and formats) and fewer like
the weakest. Don't copy the best hooks; find new angles in the same spirit."""


DEFAULT_MIX = {"loop": 30, "quick tip": 25, "relatable": 25, "workout": 20}  # loop = new test (Nov 2026)


def style_score(row, post):
    """Like score(), but watch time counts as the share of the video watched (rewatches can push it
    past 100%), so short loops and longer workouts are compared fairly."""
    from reel import video_seconds
    watch = float(row.get("avg_watch_s") or 0)
    length = video_seconds({**post, "style": row.get("style") or post.get("style", "")}) if post else 0
    if not length:
        return score(row)
    n = lambda k: int(row.get(k) or 0)
    return (n("saved") * 4 + n("shares") * 4 + real_comments(row) * 3 + round(10 * watch / length)
            + n("likes") + n("views") // 20)


def style_mix(min_each=3, age_days=2):
    """Share of next week's posts per style, tuned toward what people watch longest.
    Needs at least `min_each` judged posts per style; otherwise keeps the default mix.
    Every style keeps at least 15% so the page keeps testing (and can recover a style)."""
    now = datetime.now(TZ)
    posts = {p["id"]: p for p in load_posts()}
    by_style = {k: [] for k in DEFAULT_MIX}
    for r in load_stats().values():
        style = r.get("style") or posts.get(r["id"], {}).get("style", "")
        try:
            old_enough = (now - datetime.fromisoformat(r["published_at"]).astimezone(TZ)).days >= age_days
        except (KeyError, ValueError):
            continue
        if style in by_style and old_enough:
            by_style[style].append(style_score(r, posts.get(r["id"], {})))
    if any(len(v) < min_each for v in by_style.values()):
        return dict(DEFAULT_MIX), False
    avg = {k: max(0.5, sum(v) / len(v)) for k, v in by_style.items()}
    total = sum(avg.values())
    mix = {k: max(15, min(60, round(100 * a / total))) for k, a in avg.items()}
    top = max(mix, key=mix.get)  # make it add up to 100
    mix[top] += 100 - sum(mix.values())
    return mix, True


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never block the weekly run
        print(f"Stats step hit a problem and was skipped: {e}")
        sys.exit(0)
