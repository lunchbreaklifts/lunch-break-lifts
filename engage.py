#!/usr/bin/env python3
"""
Reply to comments on recent posts, and (with --summary) post a daily summary.

Comment replies: Claude reads each new comment and either writes a short reply in
the page's voice or skips it. It skips anything it isn't sure about: brand or collab
messages, injury/medical questions, rude or spammy comments, anything unclear.
Skipped comments that need a human are listed in the daily summary.

Daily summary: opens (and immediately closes) a GitHub issue titled
"Daily summary <date>". GitHub notifies you by email and in the GitHub app.

Needs IG_ACCESS_TOKEN (with instagram_business_manage_comments) and ANTHROPIC_API_KEY.
Never fails the workflow: problems are printed and skipped.

Usage:
    python engage.py              # reply to new comments
    python engage.py --summary    # reply, then write summary.md for the daily issue
    python engage.py --dry-run    # show what it would reply, post nothing
"""

import json
import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from common import CONFIG, ROOT, load_posts

API = f"https://graph.instagram.com/{CONFIG.get('instagram_api_version', 'v23.0')}"
TZ = ZoneInfo(CONFIG.get("timezone", "America/Denver"))
STATE = ROOT / "engage_state.json"
SUMMARY_MD = ROOT / "summary.md"
MAX_REPLIES_PER_RUN = int(CONFIG.get("max_replies_per_run", 8))
LOOKBACK_POSTS = 10
MAX_COMMENT_AGE_DAYS = 7
DRY_RUN = "--dry-run" in sys.argv
SUMMARY = "--summary" in sys.argv

REPLY_TOOL = {
    "name": "decide",
    "description": "Decide whether to reply to this Instagram comment, and write the reply.",
    "input_schema": {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["reply", "skip"]},
            "reply": {"type": "string", "description": "The reply text. Empty if skipping."},
            "needs_human": {"type": "boolean",
                            "description": "True if the page owner should personally look at this comment."},
            "reason": {"type": "string", "description": "A few words on why."},
        },
        "required": ["action", "reply", "needs_human", "reason"],
    },
}


def ig(method, path, token, **params):
    params["access_token"] = token
    if method == "POST":
        r = requests.post(f"{API}/{path}", data=params, timeout=60)
    else:
        r = requests.get(f"{API}/{path}", params=params, timeout=60)
    data = r.json()
    if "error" in data:
        raise RuntimeError(data["error"].get("message", "unknown error"))
    return data


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {"handled": {}, "log": [], "followers": {}}


def save_state(state):
    # keep the file small: only remember comments from the last 30 days
    cutoff = (datetime.now(TZ) - timedelta(days=30)).isoformat()
    state["handled"] = {k: v for k, v in state["handled"].items() if v.get("at", "") >= cutoff}
    state["log"] = [e for e in state["log"] if e.get("at", "") >= cutoff][-300:]
    state.setdefault("followers", {})  # one number per day, kept forever (tiny)
    STATE.write_text(json.dumps(state, indent=1), encoding="utf-8")


def decide(client, post, comment):
    from generate_ideas import voice_problems
    prompt = f"""You run the Instagram page "{CONFIG['page_name']}" ({CONFIG['handle']}).
{CONFIG['niche']}

Someone commented on this post:
Post headline: {post['hook']}
Post caption: {post['caption']}

Comment from @{comment['username']}: "{comment['text']}"

Decide whether to reply. Reply ONLY to normal, friendly comments you can answer well:
thanks, compliments, simple questions about the workout in the post (sets, reps, swaps,
easier/harder versions), or someone saying they tried it.

SKIP (action "skip") and set needs_human true for: brands, collabs, sponsorship or business
offers, anything about pain, injury, medical conditions, pregnancy, medication, or diet
for a health condition, and anything you'd have to guess at.
SKIP with needs_human false for: spam, bots, links, rude or trolling comments, single emojis.

If replying:
- Sound like a regular guy who lifts on his lunch break. Casual, short (under 25 words),
  lowercase is fine. Contractions. No hashtags, no links.
- At most one emoji, often none. No "Great question!" openers.
- Never claim personal experiences, results, or credentials. Never promise anything.
- Don't use em dashes or words like unlock, elevate, game-changer, level up, journey.
- If they ask something the post doesn't cover, give a short, safe, general answer
  or skip.

Call decide."""
    for _ in range(3):
        resp = client.messages.create(
            model=CONFIG.get("model", "claude-sonnet-5-5"),
            max_tokens=600,
            tools=[REPLY_TOOL],
            tool_choice={"type": "auto"},
            messages=[{"role": "user", "content": prompt}],
        )
        block = next((b for b in resp.content if b.type == "tool_use" and b.name == "decide"), None)
        if block is None:
            continue
        d = block.input
        if d.get("action") == "reply":
            text = (d.get("reply") or "").strip()
            problems = voice_problems({"hook": "", "caption": text, "slides": []})
            if not text or len(text) > 300 or problems:
                prompt += f"\n\nYour last reply was rejected ({'; '.join(problems) or 'too long or empty'}). Try again, simpler."
                continue
            d["reply"] = text
        return d
    return {"action": "skip", "reply": "", "needs_human": False, "reason": "couldn't write a clean reply"}


def collect_comments(token, me, posts):
    now = datetime.now(TZ)
    found = []
    for p in posts:
        try:
            data = ig("GET", f"{p['media_id']}/comments", token,
                      fields="id,text,username,timestamp,replies{id,username}", limit=50)
        except RuntimeError as e:
            print(f"  couldn't read comments on [{p['id']}]: {e}")
            continue
        for c in data.get("data", []):
            if c.get("username", "").lower() == me.lower():
                continue
            replies = (c.get("replies") or {}).get("data", [])
            if any(r.get("username", "").lower() == me.lower() for r in replies):
                continue
            try:
                when = datetime.fromisoformat(c["timestamp"].replace("+0000", "+00:00")).astimezone(TZ)
            except (KeyError, ValueError):
                when = now
            if (now - when).days > MAX_COMMENT_AGE_DAYS:
                continue
            found.append((p, c, when))
    found.sort(key=lambda x: x[2])
    return found


def run_replies(token, state):
    posts = [p for p in load_posts() if p["status"].lower() == "published" and p["media_id"]]
    posts = posts[-LOOKBACK_POSTS:]
    if not posts:
        print("No published posts yet.")
        return None
    me = ig("GET", "me", token, fields="username,followers_count,media_count")
    comments = [x for x in collect_comments(token, me["username"], posts) if x[1]["id"] not in state["handled"]]
    print(f"{len(comments)} new comment(s) to look at.")
    if not comments:
        return me

    import anthropic
    client = anthropic.Anthropic()
    replied = 0
    for post, c, when in comments:
        if replied >= MAX_REPLIES_PER_RUN:
            print("  reached the reply limit for this run; the rest wait for the next run.")
            break
        d = decide(client, post, c)
        entry = {"at": datetime.now(TZ).isoformat(timespec="seconds"), "post": post["id"],
                 "user": c["username"], "comment": c["text"][:300], "action": d["action"],
                 "reply": d.get("reply", ""), "needs_human": bool(d.get("needs_human")),
                 "reason": d.get("reason", "")}
        if d["action"] == "reply":
            if DRY_RUN:
                print(f"  would reply to @{c['username']}: {d['reply']}")
                continue
            try:
                ig("POST", f"{c['id']}/replies", token, message=d["reply"])
                replied += 1
                print(f"  replied to @{c['username']}: {d['reply']}")
            except RuntimeError as e:
                print(f"  reply failed for @{c['username']}: {e}")
                continue
        else:
            print(f"  skipped @{c['username']} ({d.get('reason', '')})")
        if not DRY_RUN:
            state["handled"][c["id"]] = {"at": entry["at"]}
            state["log"].append(entry)
    return me


def growth(history, now):
    """Text like ' (+3 today, +12 this week)'."""
    today = history.get(now.date().isoformat())
    if today is None:
        return ""
    parts = []
    for label, days in (("today", 1), ("this week", 7)):
        before = history.get((now.date() - timedelta(days=days)).isoformat())
        if before is not None:
            parts.append(f"{today - before:+d} {label}")
    return f" ({', '.join(parts)})" if parts else ""


def week_in_review(token, posts, now, history):
    from insights import METRICS, fetch
    week_ago = (now - timedelta(days=7)).date().isoformat()
    recent = [p for p in posts if p["published_at"][:10] > week_ago]
    lines = ["", "## Week in review"]
    start = history.get(week_ago)
    end = history.get(now.date().isoformat())
    if start is not None and end is not None:
        lines.append(f"Followers: {start} → {end} ({end - start:+d})")
    scored = []
    for p in recent:
        try:
            m = fetch(p["media_id"], token)
        except Exception:
            continue
        score = m.get("saved", 0) * 4 + m.get("shares", 0) * 4 + m.get("comments", 0) * 2 + m.get("likes", 0)
        scored.append((score, p, m))
    if not scored:
        lines.append("No post stats yet.")
        return lines
    scored.sort(key=lambda x: x[0], reverse=True)
    total_views = sum(m.get("views", 0) for _, _, m in scored)
    lines.append(f"{len(scored)} posts, {total_views} views total.")
    best, worst = scored[0], scored[-1]
    lines.append(f"**Best:** {best[1]['hook']} ({best[1].get('format') or 'post'}): "
                 + " · ".join(f"{k} {best[2].get(k, 0)}" for k in METRICS))
    if len(scored) > 1:
        lines.append(f"**Weakest:** {worst[1]['hook']}: views {worst[2].get('views', 0)}")
    lines.append("The robot feeds these into next week's posts automatically.")
    return lines


def write_summary(token, state, me):
    from insights import METRICS, fetch
    now = datetime.now(TZ)
    since = (now - timedelta(days=1)).isoformat()
    lines = [f"# Daily summary for {CONFIG['handle']}, {now:%a %b %-d}", ""]

    history = state.setdefault("followers", {})
    if me and isinstance(me.get("followers_count"), int):
        history[now.date().isoformat()] = me["followers_count"]
    if me:
        count = me.get("followers_count", "?")
        lines.append(f"**Followers:** {count}{growth(history, now)}  |  **Posts:** {me.get('media_count', '?')}")
        lines.append("")

    posts = [p for p in load_posts() if p["status"].lower() == "published" and p["media_id"]]
    today = [p for p in posts if p["published_at"][:10] == now.date().isoformat()]
    if today:
        p = today[-1]
        lines.append(f"## Today's post ({p.get('format') or 'post'})")
        lines.append(f"{p['hook']}")
        try:
            m = fetch(p["media_id"], token)
            lines.append(" · ".join(f"{k} {m.get(k, 0)}" for k in METRICS))
        except Exception:
            lines.append("(stats not ready yet)")
        lines.append("")
    else:
        lines += ["## Today's post", "Nothing went out today. Check the Actions tab if that's unexpected.", ""]

    recent = [e for e in state["log"] if e.get("at", "") >= since]
    needs = [e for e in recent if e.get("needs_human")]
    replied = [e for e in recent if e["action"] == "reply"]
    lines.append(f"## Comments (last 24 hours): {len(recent)} new, {len(replied)} answered by the robot")
    if needs:
        lines += ["", "### 👉 Needs you"]
        lines += [f"- @{e['user']}: \"{e['comment']}\" ({e['reason']})" for e in needs]
    if replied:
        lines += ["", "### Robot replies"]
        lines += [f"- @{e['user']}: \"{e['comment']}\"  \n  ↳ {e['reply']}" for e in replied]
    lines += ["", "Check your Instagram DMs too. The robot doesn't read or answer those."]

    if now.weekday() == 6:  # Sunday
        lines += week_in_review(token, posts, now, history)

    queue = sum(1 for p in load_posts() if p["status"].lower() == "rendered")
    lines += ["", f"_Posts waiting in the queue: {queue}_"]
    if queue < 2:
        lines.append("⚠️ The queue is almost empty. The Sunday job refills it; if that job failed, "
                     "open Actions > Weekly content > Run workflow.")
    SUMMARY_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {SUMMARY_MD.name}")


def main():
    if not CONFIG.get("auto_reply_comments", True) and not SUMMARY:
        print('Comment replies are turned off ("auto_reply_comments": false).')
        return
    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if not token:
        print("No IG_ACCESS_TOKEN set; skipping.")
        return
    state = load_state()
    me = None
    if CONFIG.get("auto_reply_comments", True):
        if not os.environ.get("ANTHROPIC_API_KEY"):
            print("No ANTHROPIC_API_KEY set; skipping replies.")
        else:
            me = run_replies(token, state)
    if not DRY_RUN:
        save_state(state)
    if SUMMARY:
        if me is None:
            try:
                me = ig("GET", "me", token, fields="username,followers_count,media_count")
            except Exception:
                me = None
        write_summary(token, state, me)
        if not DRY_RUN:
            save_state(state)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # never block anything else
        print(f"Engage step hit a problem and was skipped: {e}")
        sys.exit(0)
