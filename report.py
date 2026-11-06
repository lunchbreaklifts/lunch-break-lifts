#!/usr/bin/env python3
"""
Build report/index.html: a phone-friendly page with how the page is doing. Rebuilt every
night after the stats refresh, and served by GitHub Pages at
https://lunchbreaklifts.github.io/lunch-break-lifts/report/

Only the page's own numbers are shown (followers, views, likes...). No follower names or
comments. The link isn't listed anywhere and search engines are asked not to index it,
but anyone with the link can open it.
"""

import html
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from common import CONFIG, ROOT, load_posts

TZ = ZoneInfo(CONFIG.get("timezone", "America/Denver"))
OUT = ROOT / "report" / "index.html"
B = CONFIG["brand"]


def load():
    from insights import load_stats
    stats = load_stats()
    posts = {p["id"]: p for p in load_posts()}
    try:
        followers = json.loads((ROOT / "engage_state.json").read_text(encoding="utf-8")).get("followers", {})
    except (FileNotFoundError, ValueError):
        followers = {}
    rows = []
    for pid, st in stats.items():
        p = posts.get(pid, {})
        try:
            when = datetime.fromisoformat(st["published_at"]).astimezone(TZ)
        except (KeyError, ValueError):
            continue
        n = lambda k: int(st.get(k) or 0)
        rows.append({"id": pid, "hook": st.get("hook") or p.get("hook", ""), "when": when,
                     "format": st.get("format") or p.get("format") or "post", "audio": p.get("audio", ""),
                     "style": p.get("style", ""), "watch": float(st.get("avg_watch_s") or 0),
                     "challenge": p.get("series") == "challenge",
                     **{k: n(k) for k in ("views", "reach", "likes", "comments", "shares", "saved")}})
    rows.sort(key=lambda r: r["when"])
    return rows, dict(sorted(followers.items()))


def avg(rows, key="views"):
    return round(sum(r[key] for r in rows) / len(rows)) if rows else 0


# ---------------------------------------------------------------- tiny SVG charts
def line_chart(points, w=640, h=200):
    if len(points) < 2:
        return "<p class='muted'>Not enough days yet. Check back in a few days.</p>"
    vals = [v for _, v in points]
    lo, hi = min(vals), max(vals)
    hi = hi if hi > lo else lo + 1
    pad = 28
    xs = [pad + i * (w - 2 * pad) / (len(points) - 1) for i in range(len(points))]
    ys = [h - pad - (v - lo) * (h - 2 * pad) / (hi - lo) for v in vals]
    path = " ".join(f"{'M' if i == 0 else 'L'}{x:.1f},{y:.1f}" for i, (x, y) in enumerate(zip(xs, ys)))
    area = path + f" L{xs[-1]:.1f},{h - pad} L{xs[0]:.1f},{h - pad} Z"
    labels = (f"<text x='{xs[0]:.0f}' y='{h - 6}' class='ax'>{points[0][0][5:]}</text>"
              f"<text x='{xs[-1]:.0f}' y='{h - 6}' class='ax' text-anchor='end'>{points[-1][0][5:]}</text>"
              f"<text x='{pad - 6}' y='{ys[vals.index(hi) if hi in vals else 0]:.0f}' class='ax' text-anchor='end'>{max(vals)}</text>"
              f"<text x='{pad - 6}' y='{h - pad:.0f}' class='ax' text-anchor='end'>{lo}</text>")
    return (f"<svg viewBox='0 0 {w} {h}' role='img' aria-label='Followers over time, from {vals[0]} to {vals[-1]}'>"
            f"<path d='{area}' fill='{B['accent']}' opacity='.12'/>"
            f"<path d='{path}' fill='none' stroke='{B['accent']}' stroke-width='3' stroke-linejoin='round'/>"
            f"<circle cx='{xs[-1]:.1f}' cy='{ys[-1]:.1f}' r='5' fill='{B['accent']}'/>{labels}</svg>")


def bar_chart(rows, w=640, h=220):
    rows = rows[-14:]
    if not rows:
        return "<p class='muted'>No posts with stats yet.</p>"
    hi = max(r["views"] for r in rows) or 1
    pad, gap = 24, 6
    bw = (w - 2 * pad - gap * (len(rows) - 1)) / len(rows)
    bars = []
    for i, r in enumerate(rows):
        bh = max(2, r["views"] / hi * (h - 2 * pad))
        x = pad + i * (bw + gap)
        color = B["accent"] if r["format"] == "reel" else B["muted"]
        bars.append(f"<rect x='{x:.1f}' y='{h - pad - bh:.1f}' width='{bw:.1f}' height='{bh:.1f}' rx='3' fill='{color}'>"
                    f"<title>{html.escape(r['hook'])}: {r['views']} views</title></rect>"
                    f"<text x='{x + bw / 2:.1f}' y='{h - pad - bh - 5:.1f}' class='ax' text-anchor='middle'>{r['views']}</text>")
    return (f"<svg viewBox='0 0 {w} {h}' role='img' aria-label='Views per post for the last {len(rows)} posts'>"
            + "".join(bars) + "</svg>"
            f"<p class='legend'><span class='dot' style='background:{B['accent']}'></span>Reel "
            f"<span class='dot' style='background:{B['muted']}'></span>Carousel</p>")


# ---------------------------------------------------------------- page
def compare(label, a_name, a, b_name, b):
    if not a or not b:
        return ""
    va, vb = avg(a), avg(b)
    win = a_name if va >= vb else b_name
    return (f"<tr><td>{label}</td><td>{a_name} <b>{va}</b> vs {b_name} <b>{vb}</b></td>"
            f"<td class='win'>{html.escape(win)}</td></tr>")


def build():
    rows, followers = load()
    now = datetime.now(TZ)
    week = [r for r in rows if r["when"] >= now - timedelta(days=7)]
    fol_now = list(followers.values())[-1] if followers else 0
    week_ago = (now - timedelta(days=7)).date().isoformat()
    base = next((v for d, v in followers.items() if d >= week_ago), fol_now)
    judged = [r for r in rows if (now - r["when"]).days >= 2]
    reels = [r for r in judged if r["format"] == "reel"]

    tiles = [("Followers", fol_now, f"{fol_now - base:+d} this week"),
             ("Posts this week", len(week), f"{sum(r['views'] for r in week):,} views total"),
             ("Avg views per Reel", avg(reels), f"{len(reels)} Reels so far"),
             ("Avg watch time", f"{(sum(r['watch'] for r in reels if r['watch']) / max(1, len([r for r in reels if r['watch']]))):.1f}s",
              "per Reel view. Higher = Instagram pushes it more"),
             ("Saves + shares", sum(r["saved"] + r["shares"] for r in rows), "all time, the growth signal")]
    tile_html = "".join(f"<div class='tile'><div class='k'>{k}</div><div class='v'>{v}</div>"
                        f"<div class='s'>{html.escape(s)}</div></div>" for k, v, s in tiles)

    top = sorted(rows, key=lambda r: r["views"], reverse=True)[:5]
    top_html = "".join(
        f"<li><div class='hook'>{html.escape(r['hook'])}</div><div class='meta'>{r['when']:%b %-d} · "
        f"{r['format']} · <b>{r['views']}</b> views · {r['likes']} likes · {r['saved']} saves · {r['shares']} shares</div></li>"
        for r in top) or "<li class='muted'>No posts yet.</li>"

    lunch = [r for r in judged if r["when"].hour < 15]
    comp = "".join(filter(None, [
        compare("Format", "Reels", reels, "carousels", [r for r in judged if r["format"] != "reel"]),
        compare("Music", "song", [r for r in reels if r["audio"]], "no song", [r for r in reels if not r["audio"]]),
        compare("Time", "lunch", lunch, "evening", [r for r in judged if r not in lunch]),
        compare("Style", "quick tip", [r for r in judged if r["style"] == "quick tip"],
                "workout", [r for r in judged if r["style"] == "workout"]),
        compare("Style", "relatable", [r for r in judged if r["style"] == "relatable"],
                "workout", [r for r in judged if r["style"] == "workout"]),
        compare("Series", "challenge", [r for r in judged if r["challenge"]], "regular", [r for r in judged if not r["challenge"]]),
    ])) or "<tr><td colspan='3' class='muted'>Needs a few more posts to compare.</td></tr>"

    recent_html = "".join(
        f"<tr><td>{r['when']:%b %-d %-I%p}</td><td>{html.escape(r['hook'][:60])}</td><td>{r['views']}</td>"
        f"<td>{(str(r['watch']) + 's') if r['watch'] else '-'}</td><td>{r['likes']}</td><td>{r['saved']}</td></tr>"
        for r in reversed(rows[-10:]))

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow">
<title>Page report | Lunch Break Lifts</title>
<style>
:root{{--bg:{B['background']};--text:{B['text']};--muted:{B['muted']};--accent:{B['accent']};--card:#171a20;--line:#262a31}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--text);
font:16px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;padding:20px 16px 48px}}
.wrap{{max-width:760px;margin:0 auto}} h1{{font-size:26px;margin:0}} .muted{{color:var(--muted)}}
h2{{font-size:15px;text-transform:uppercase;letter-spacing:.06em;color:var(--accent);margin:30px 0 10px}}
.tiles{{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin-top:18px}}
@media(min-width:640px){{.tiles{{grid-template-columns:repeat(5,1fr)}}}}
.tile{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}}
.tile .k{{font-size:13px;color:var(--muted)}} .tile .v{{font-size:30px;font-weight:800;margin:2px 0}}
.tile .s{{font-size:12px;color:var(--muted)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;overflow-x:auto}}
svg{{width:100%;height:auto;display:block}} .ax{{fill:var(--muted);font-size:12px}}
.legend{{font-size:13px;color:var(--muted);margin:6px 0 0}} .dot{{display:inline-block;width:10px;height:10px;border-radius:2px;margin:0 4px 0 10px}}
ol{{margin:0;padding-left:22px}} li{{margin:10px 0}} .hook{{font-weight:600}} .meta{{font-size:13px;color:var(--muted)}}
table{{width:100%;border-collapse:collapse;font-size:14px}} td,th{{padding:8px 6px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}}
th{{color:var(--muted);font-weight:600;font-size:12px;text-transform:uppercase}} .win{{color:var(--accent);font-weight:700;white-space:nowrap}}
</style></head><body><div class="wrap">
<h1>Lunch Break Lifts</h1><div class="muted">Updated {now:%a %b %-d, %-I:%M %p}. Rebuilt every night.</div>
<div class="tiles">{tile_html}</div>
<h2>Followers</h2><div class="card">{line_chart(list(followers.items()))}</div>
<h2>Views per post (last 14)</h2><div class="card">{bar_chart(rows)}</div>
<h2>Top 5 posts</h2><div class="card"><ol>{top_html}</ol></div>
<h2>What's working (average views)</h2><div class="card"><table>{comp}</table>
<p class="legend">Posts under 2 days old aren't counted yet.</p></div>
<h2>Latest posts</h2><div class="card"><table><tr><th>When</th><th>Post</th><th>Views</th><th>Watched</th><th>Likes</th><th>Saves</th></tr>{recent_html}</table></div>
</div></body></html>
"""
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(page, encoding="utf-8")
    print(f"Wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    try:
        build()
    except Exception as e:
        print(f"Report skipped: {e}")
