#!/usr/bin/env python3
"""
The 30-Day Lunch Break Challenge: the free plan people get by commenting LIFT, and the
source for the daily "Day N/30" challenge posts.

    python challenge.py          # rebuild challenge.json and plan/index.html

Five training days a week (25-35 min), plus easy days on weekends. Dumbbells or
bodyweight. Each week adds a little: more sets, more reps, shorter rest.
"""

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# ---------------------------------------------------------------- workouts
WARMUP = "Warm-up (4 min): 10 bodyweight squats, 10 arm circles each way, 8 inchworms, 20 sec plank."


def upper(week):
    sets = [2, 3, 3, 4][week]
    reps = ["8-10", "8-10", "10-12", "8-10 (go heavier)"][week]
    rest = ["75 sec", "75 sec", "60 sec", "60 sec"][week]
    return {
        "title": "Upper body: push and pull",
        "minutes": [25, 30, 30, 35][week],
        "blocks": [
            WARMUP,
            f"A1. Dumbbell floor press: {sets} x {reps}",
            f"A2. One-arm dumbbell row: {sets} x {reps} each side. Rest {rest} after both.",
            f"B1. Seated dumbbell shoulder press: {sets} x {reps}",
            f"B2. Band pull-apart: {sets} x 15 (no band: prone Y raise x 10). Rest {rest}.",
            f"C. Push-ups: {sets} sets, stop 2 reps before you can't. Elevate your hands on a desk if needed.",
        ],
        "tip": ["Pick a weight you could lift 2-3 more times. That's the right weight.",
                "Same weights as last week, one more set.",
                "Shorter rest today. Keep the form, not the pace.",
                "Go up one dumbbell size on the press and row if last week felt easy."][week],
    }


def lower(week):
    sets = [2, 3, 3, 4][week]
    reps = ["10", "10", "12", "10 (heavier)"][week]
    return {
        "title": "Lower body",
        "minutes": [25, 30, 30, 35][week],
        "blocks": [
            WARMUP,
            f"A. Goblet squat: {sets} x {reps}. Rest 75 sec.",
            f"B. Dumbbell Romanian deadlift: {sets} x {reps}. Rest 75 sec.",
            f"C1. Reverse lunge: {sets} x 8 each leg",
            f"C2. Glute bridge: {sets} x 12. Rest 60 sec after both.",
            f"D. Farmer carry: {sets} x 40 steps, heavy as you can hold with good posture.",
        ],
        "tip": ["Sit down between your heels on the squat. Chest up, slow on the way down.",
                "On the RDL, push your hips back like closing a car door with your butt.",
                "If your legs are sore from last time, that's normal. Move anyway, it helps.",
                "Last week of the challenge for legs. Make the farmer carry heavy."][week],
    }


def full_body(week):
    rounds = [3, 3, 4, 4][week]
    work = ["30 sec work / 30 sec rest", "35 sec work / 25 sec rest",
            "40 sec work / 20 sec rest", "40 sec work / 20 sec rest"][week]
    return {
        "title": "Full-body circuit",
        "minutes": [24, 24, 30, 30][week],
        "blocks": [
            WARMUP,
            f"{rounds} rounds, {work}:",
            "1. Dumbbell thruster (squat into a press)",
            "2. Push-ups (hands on a desk if needed)",
            "3. Bent-over dumbbell row",
            "4. Reverse lunge, alternating legs",
            "5. Dead bug",
            "Rest 1 minute between rounds.",
        ],
        "tip": ["Light weights. This one is about moving well and breathing hard, not max effort.",
                "Try to get the same number of reps in every round.",
                "Four rounds now. Pace the first one.",
                "Same as last week. Try to beat your reps from Week 3."][week],
    }


def conditioning(week):
    minutes = [12, 14, 16, 18][week]
    return {
        "title": "Conditioning + core",
        "minutes": [22, 24, 26, 28][week],
        "blocks": [
            WARMUP,
            f"EMOM for {minutes} minutes (start a new set at the top of every minute, rest the remainder):",
            "Odd minutes: 8 goblet squats + 6 push-ups",
            "Even minutes: 10 mountain climbers each side + 8 dumbbell swings (or 10 jump squats)",
            "Core finisher, 2 rounds: 30 sec plank, 20 sec side plank each side, 10 bird dogs each side.",
        ],
        "tip": ["If you can't finish inside the minute, cut the reps. Don't skip the rest.",
                "Two more minutes than last week. Same rhythm.",
                "You'll be sweaty. Bring a towel and a fresh shirt.",
                "Last conditioning day. Push the even minutes."][week],
    }


def walk(week):
    return {
        "title": "Easy day: walk + mobility",
        "minutes": 20,
        "blocks": [
            f"Brisk walk, {[15, 15, 20, 20][week]} minutes. Phone in your pocket.",
            "Then 5 minutes: hip flexor stretch 30 sec each side, doorway chest stretch 30 sec, "
            "cat-cow x 10, child's pose 60 sec.",
        ],
        "tip": "Easy days are part of the plan. They're why the hard days keep working.",
    }


def rest(week):
    return {
        "title": "Rest + stretch",
        "minutes": 10,
        "blocks": ["10 minutes of easy stretching anytime today: hamstrings, hips, chest, upper back."],
        "tip": "Sleep and food do the building. Take the day.",
    }


# Day 1 is a Monday.
WEEK = [upper, lower, walk, full_body, conditioning, walk, rest]


def build():
    days = []
    for d in range(1, 31):
        week = min((d - 1) // 7, 3)
        maker = WEEK[(d - 1) % 7]
        day = maker(week)
        if d == 29:
            day = dict(upper(0), title="Test day: repeat Day 1",
                       tip="Same workout as Day 1. Write down your weights and reps. Compare. That's your proof.")
        if d == 30:
            day = {"title": "Finish line: walk, stretch, plan what's next", "minutes": 20,
                   "blocks": ["20 minute walk.", "Pick your 3 favorite workouts from this month and put them on "
                              "your calendar for next week, same time as today."],
                   "tip": "You made the time 30 days in a row. Keep the slot. The slot is the habit."}
        day["day"] = d
        day["week"] = week + 1
        days.append(day)
    return days


# ---------------------------------------------------------------- page
PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>30-Day Lunch Break Challenge | Lunch Break Lifts</title>
<meta name="description" content="A free 30-day lunch break workout plan: 25-35 minutes, dumbbells or bodyweight.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Archivo+Black&family=Inter:wght@400;500;700&display=swap" rel="stylesheet">
<style>
:root{--bg:#0F1115;--card:#171a20;--text:#F4F4F2;--muted:#8A8F98;--accent:#C6F432;--line:#262a31}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:16px/1.55 Inter,system-ui,sans-serif;
padding:24px max(16px,env(safe-area-inset-left)) 64px}
.wrap{max-width:720px;margin:0 auto}
h1{font:400 clamp(32px,8vw,52px)/1.02 'Archivo Black',Impact,sans-serif;text-transform:uppercase;margin:8px 0 12px}
.eyebrow{color:var(--muted);font-weight:700;letter-spacing:.08em;font-size:13px;text-transform:uppercase}
.bar{width:72px;height:8px;background:var(--accent);margin:18px 0}
.lead{color:#cfd2d6;max-width:60ch}
.how{border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin:20px 0 28px;color:#cfd2d6}
.how b{color:var(--accent)}
h2{font:400 22px 'Archivo Black',Impact,sans-serif;text-transform:uppercase;margin:36px 0 12px;color:var(--accent)}
details{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:8px 0}
summary{cursor:pointer;padding:14px 16px;display:flex;gap:12px;align-items:baseline;list-style:none}
summary::-webkit-details-marker{display:none}
.n{font:400 15px 'Archivo Black',sans-serif;color:var(--accent);min-width:58px}
.t{font-weight:700;flex:1}
.m{color:var(--muted);font-size:14px;white-space:nowrap}
.body{padding:0 16px 14px 86px}
.body ul{margin:0;padding-left:18px}
.body li{margin:4px 0}
.tip{color:var(--muted);font-size:14px;margin-top:10px}
.tip:before{content:"Tip: ";color:var(--accent);font-weight:700}
.foot{color:var(--muted);font-size:13px;margin-top:40px;border-top:1px solid var(--line);padding-top:16px}
@media (max-width:520px){.body{padding-left:16px}.n{min-width:50px}}
@media print{body{background:#fff;color:#000}details{border-color:#ccc;background:#fff;break-inside:avoid}
details>.body{display:block}.how,.lead{color:#000}h2,.n{color:#000}.tip,.m{color:#444}}
</style></head><body><div class="wrap">
<div class="eyebrow">Lunch Break Lifts &middot; @lunch_breaklifts</div>
<h1>30-Day Lunch Break Challenge</h1>
<div class="bar"></div>
<p class="lead">Thirty days, one lunch break each. 25 to 35 minutes, dumbbells or just bodyweight.
Five training days a week, easy days on the weekend. Each week adds a little.</p>
<div class="how"><b>How to use it:</b> do the day that matches, at the same time each day.
Tap a day to open it. If you miss one, just do today's. Write your weights down on Day 1;
you'll need them on Day 29.<br><br>
<b>Safety:</b> this is general fitness info for healthy adults, not medical advice.
If something hurts (not just hard, actually hurts), stop and check with a doctor.</div>
{weeks}
<div class="foot">Free from @lunch_breaklifts on Instagram. A new lunch workout every day.
Questions? Comment on any post.</div>
</div></body></html>
"""


def page(days):
    out = []
    for w in range(1, 6):
        wk = [d for d in days if d["week"] == w] if w < 5 else []
        if not wk:
            continue
        label = f"Week {w}" if w < 4 else "Week 4 + finish"
        out.append(f"<h2>{label}</h2>")
        for d in wk:
            items = "".join(f"<li>{html.escape(b)}</li>" for b in d["blocks"])
            out.append(
                f'<details{" open" if d["day"] == 1 else ""}><summary><span class="n">Day {d["day"]}</span>'
                f'<span class="t">{html.escape(d["title"])}</span><span class="m">{d["minutes"]} min</span></summary>'
                f'<div class="body"><ul>{items}</ul><div class="tip">{html.escape(d["tip"])}</div></div></details>'
            )
    return PAGE.replace("{weeks}", "\n".join(out))


if __name__ == "__main__":
    days = build()
    (ROOT / "challenge.json").write_text(json.dumps(days, indent=1), encoding="utf-8")
    (ROOT / "plan").mkdir(exist_ok=True)
    (ROOT / "plan" / "index.html").write_text(page(days), encoding="utf-8")
    print(f"Wrote challenge.json ({len(days)} days) and plan/index.html")
