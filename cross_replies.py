"""
Reply to comments on the copies of each post on Facebook, Threads and YouTube, the same way
engage.py does on Instagram: same voice, same skip rules, same privacy (no names or comment
text are ever saved or printed; the repo is public).

Each platform is skipped quietly if its key is missing or lacks the reply permission:
    Facebook  FB_PAGE_TOKEN with pages_read_engagement + pages_manage_engagement
    Threads   THREADS_TOKEN with threads_read_replies + threads_manage_replies
    YouTube   YT_* keys with the youtube.force-ssl scope

On these platforms there's no private-message option, so someone who comments the plan
keyword gets the plan link as a reply instead.
"""

import os
import random
from datetime import datetime, timedelta

import requests

from common import CONFIG, load_posts

LOOKBACK_POSTS = 10
MAX_AGE_DAYS = 7
PLAN_REPLIES = ["Here you go, all 30 days: {url}", "Here's the full 30-day plan: {url}",
                "All 30 days are here: {url} 💪"]


def _recent_posts(field):
    posts = [p for p in load_posts() if p["status"].lower() == "published" and p.get(field)]
    return posts[-LOOKBACK_POSTS:]


def _fresh(ts, now):
    try:
        when = datetime.fromisoformat(ts.replace("Z", "+00:00").replace("+0000", "+00:00"))
    except (ValueError, AttributeError):
        return True
    return now - when.astimezone(now.tzinfo) <= timedelta(days=MAX_AGE_DAYS)


# ---------------------------------------------------------------- Facebook
def facebook_comments(posts, now):
    tok = os.environ.get("FB_PAGE_TOKEN", "").strip()
    if not tok or not CONFIG.get("facebook_reels", True):
        return None, []
    from facebook import GRAPH, page_token
    pt = page_token(tok)
    page_id = CONFIG.get("facebook_page_id", "")
    out = []
    for p in posts:
        r = requests.get(f"{GRAPH}/{p['facebook_id']}/comments", timeout=30, params={
            "fields": "id,message,from{id},created_time", "filter": "toplevel", "limit": 50,
            "access_token": pt}).json()
        if "error" in r:
            raise RuntimeError(r["error"].get("message", "unknown error"))
        for c in r.get("data", []):
            if (c.get("from") or {}).get("id") == page_id or not _fresh(c.get("created_time", ""), now):
                continue
            out.append((p, {"id": f"fb:{c['id']}", "raw_id": c["id"], "text": c.get("message", ""),
                            "from": {"id": f"fb:{(c.get('from') or {}).get('id', c['id'])}"}}))

    def reply(c, text):
        r = requests.post(f"{GRAPH}/{c['raw_id']}/comments", data={"message": text, "access_token": pt},
                          timeout=30).json()
        if "error" in r:
            raise RuntimeError(r["error"].get("message", "unknown error"))
    return reply, out


# ---------------------------------------------------------------- Threads
def threads_comments(posts, now):
    tok = os.environ.get("THREADS_TOKEN", "").strip()
    if not tok or not CONFIG.get("threads", True):
        return None, []
    from threads import API, _call
    me = _call("GET", "me", tok, fields="username").get("username", "")
    out = []
    for p in posts:
        data = _call("GET", f"{p['threads_id']}/replies", tok, fields="id,text,username,timestamp")
        for c in data.get("data", []):
            if c.get("username", "").lower() == me.lower() or not _fresh(c.get("timestamp", ""), now):
                continue
            out.append((p, {"id": f"th:{c['id']}", "raw_id": c["id"], "text": c.get("text", ""),
                            "from": {"id": f"th:{c.get('username', c['id'])}"}}))

    def reply(c, text):
        container = _call("POST", "me/threads", tok, media_type="TEXT", text=text, reply_to_id=c["raw_id"])["id"]
        _call("POST", "me/threads_publish", tok, creation_id=container)
    return reply, out


# ---------------------------------------------------------------- YouTube
def youtube_comments(posts, now):
    import youtube
    if not youtube.configured() or not CONFIG.get("youtube_shorts", True):
        return None, []
    token = youtube.access_token()
    h = {"Authorization": f"Bearer {token}"}
    mine = requests.get(f"{youtube.API}/channels", params={"part": "id", "mine": "true"}, headers=h,
                        timeout=30).json().get("items", [{}])[0].get("id", "")
    out = []
    for p in posts:
        r = requests.get(f"{youtube.API}/commentThreads", headers=h, timeout=30, params={
            "part": "snippet", "videoId": p["youtube_id"], "maxResults": 50, "textFormat": "plainText"}).json()
        if "error" in r:
            raise RuntimeError(r["error"].get("message", "unknown error"))
        for t in r.get("items", []):
            top = t["snippet"]["topLevelComment"]["snippet"]
            author = (top.get("authorChannelId") or {}).get("value", "")
            if author == mine:
                continue
            if not _fresh(top.get("publishedAt", ""), now):
                continue
            out.append((p, {"id": f"yt:{t['id']}", "raw_id": t["id"], "text": top.get("textOriginal", ""),
                            "from": {"id": f"yt:{author or t['id']}"}}))

    def reply(c, text):
        r = requests.post(f"{youtube.API}/comments", params={"part": "snippet"}, headers=h, timeout=30,
                          json={"snippet": {"parentId": c["raw_id"], "textOriginal": text}})
        if r.status_code >= 400:
            raise RuntimeError(r.json().get("error", {}).get("message", f"HTTP {r.status_code}"))
    return reply, out


PLATFORMS = [("Facebook", "facebook_id", facebook_comments),
             ("Threads", "threads_id", threads_comments),
             ("YouTube", "youtube_id", youtube_comments)]


def run_all(state, client, max_replies=8):
    """Reply on every other platform. Never raises."""
    import engage
    now = datetime.now(engage.TZ)
    lead = CONFIG.get("lead_magnet", {})
    notes = state.setdefault("cross_notes", {})
    for name, field, fetch in PLATFORMS:
        posts = _recent_posts(field)
        if not posts:
            continue
        try:
            reply, comments = fetch(posts, now)
        except Exception as e:
            msg = str(e)[:160]
            if notes.get(name) != msg:
                print(f"  {name}: can't read comments yet ({msg})")
            notes[name] = msg
            continue
        if reply is None:
            continue
        notes.pop(name, None)
        todo, seen = [], set()
        for p, c in comments:
            if c["id"] not in state["handled"] and c["id"] not in seen:
                seen.add(c["id"])
                todo.append((p, c))
        if todo:
            print(f"  {name}: {len(todo)} new comment(s)")
        done = 0
        for post, c in todo:
            if done >= max_replies:
                break
            code = engage.who(c)
            at = now.isoformat(timespec="seconds")
            if code in state.get("forget", []):
                state["handled"][c["id"]] = {"at": at}
                continue
            entry = {"at": at, "post": post["id"], "cid": c["id"], "who": code, "platform": name,
                     "reply": "", "needs_human": False, "question": False}
            if engage.wants_plan(c["text"]):
                text = random.choice(PLAN_REPLIES).format(url=lead.get("url", ""))
                entry.update(action="plan link", reason="asked for the free plan")
            else:
                d = engage.decide(client, post, {"text": c["text"]})
                if d.get("reason") not in engage.REPLY_TOOL["input_schema"]["properties"]["reason"]["enum"]:
                    d["reason"] = "other"
                entry.update(action=d["action"], reason=d["reason"], needs_human=bool(d.get("needs_human")))
                text = d.get("reply", "") if d["action"] == "reply" else ""
            if text and not engage.DRY_RUN:
                try:
                    reply(c, text)
                    done += 1
                    entry["reply"] = text
                    print(f"  {name}: replied to comment {c['id']}: {text}")
                except Exception as e:
                    print(f"  {name}: reply failed ({str(e)[:160]})")
                    if "permission" in str(e).lower() or "scope" in str(e).lower():
                        notes[name] = f"needs reply permission: {str(e)[:120]}"
                        break
                    continue
            elif text:
                print(f"  {name}: would reply to {c['id']}: {text}")
                continue
            if not engage.DRY_RUN:
                state["handled"][c["id"]] = {"at": at}
                state["log"].append(entry)
