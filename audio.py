#!/usr/bin/env python3
"""
Pick a trending, clean song for a Reel using Instagram's Audio API.

The Audio API only works through the Facebook-login side of the Instagram API, so it
needs FB_PAGE_TOKEN (a Page access token for the Facebook Page linked to the
Instagram account). Without it, Reels just go out without music.

How a song is chosen:
  1. Get what's trending on Instagram right now, plus a few workout-related searches.
  2. Drop anything with explicit words in the title, anything too short for the Reel,
     and anything used in the last few weeks (so the page never gets stale).
  3. Ask Claude to pick the one that best fits a lunch-break workout video
     (upbeat, clean, not a lullaby or a sad ballad). If that fails, pick at random
     from the top of the trending list.

Usage (for testing):
    python audio.py              # print the song it would pick
"""

import json
import os
import random
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from common import CONFIG, ROOT

FB_API = f"https://graph.facebook.com/{CONFIG.get('facebook_api_version', 'v23.0')}"
TZ = ZoneInfo(CONFIG.get("timezone", "America/Denver"))
USED_FILE = ROOT / "audio_used.json"
NO_REPEAT_DAYS = int(CONFIG.get("audio_no_repeat_days", 21))
SEARCHES = CONFIG.get("audio_searches", ["workout", "gym", "motivation"])

EXPLICIT = re.compile(
    r"f+u+c+k|sh[i1]t|b[i1]tch|\bass\b|asshole|d[i1]ck|pussy|n[i1]gg|wh[o0]re|sl[u]t|"
    r"\bhoe\b|damn|explicit|\bsex|cocaine|weed|kill|"
    r"hala madrid|anthem|\bf\.?c\.?\b|lullaby|sleep|rain sounds|white noise|meditation",
    re.IGNORECASE,
)


def fb_get(path, token, **params):
    params["access_token"] = token
    r = requests.get(f"{FB_API}/{path}", params=params, timeout=60)
    data = r.json()
    if "error" in data:
        raise RuntimeError(data["error"].get("message", "unknown error"))
    return data


def load_used():
    try:
        return json.loads(USED_FILE.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def mark_used(audio):
    used = load_used()
    now = datetime.now(TZ)
    used[audio["audio_id"]] = {"at": now.isoformat(timespec="seconds"),
                               "title": audio.get("title", ""), "artist": audio.get("display_artist", "")}
    cutoff = (now - timedelta(days=90)).isoformat()
    used = {k: v for k, v in used.items() if v.get("at", "") >= cutoff}
    USED_FILE.write_text(json.dumps(used, indent=1), encoding="utf-8")


def candidates(ig_user_id, token):
    """Trending music first, then a few workout searches. De-duplicated, in that order."""
    seen, out = set(), []
    queries = [None] + list(SEARCHES)
    for q in queries:
        params = {"audio_type": "music", "user_id": ig_user_id}
        if q:
            params["search_query"] = q
        try:
            items = fb_get("ig_audio", token, **params).get("audio", [])
        except RuntimeError as e:
            print(f"    audio search {q or 'trending'!r} failed: {e}")
            continue
        for a in items:
            key = (a.get("title", "").lower(), a.get("display_artist", "").lower())
            if not a.get("audio_id") or key in seen:
                continue
            seen.add(key)
            a["_source"] = q or "trending"
            out.append(a)
    return out


def usable(items, reel_seconds):
    used = load_used()
    cutoff = (datetime.now(TZ) - timedelta(days=NO_REPEAT_DAYS)).isoformat()
    recent_ids = {k for k, v in used.items() if v.get("at", "") >= cutoff}
    recent_titles = {v.get("title", "").lower() for k, v in used.items() if v.get("at", "") >= cutoff}
    keep = []
    for a in items:
        text = f"{a.get('title', '')} {a.get('display_artist', '')}"
        if EXPLICIT.search(text):
            continue
        if a["audio_id"] in recent_ids or a.get("title", "").lower() in recent_titles:
            continue
        if (a.get("duration_in_ms") or 0) < reel_seconds * 1000:
            continue
        keep.append(a)
    return keep


def claude_pick(options, hook):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic
    except ImportError:
        return None
    listing = "\n".join(f"{i}. {a.get('title')} | {a.get('display_artist')} | {a['_source']}"
                        for i, a in enumerate(options))
    prompt = f"""Pick background music for an Instagram Reel from a fitness page for busy office workers
who lift on their lunch break. Today's Reel: "{hook}"

Choose ONE song from this list (title | artist | found via). It MUST be energetic or have a
steady driving beat, suit a gym/workout video, and be fine to play at work. Among those, prefer
ones found via "trending". Never pick: sad or slow songs, lullabies, love ballads, songs known for
explicit lyrics, sports team or club anthems, comedy or meme sounds, holiday songs.

{listing}

Reply in this exact form:
PICK: <number>
WHY: <a few words>"""
    try:
        resp = anthropic.Anthropic().messages.create(
            model=CONFIG.get("model", "claude-sonnet-5-5"), max_tokens=60,
            messages=[{"role": "user", "content": prompt}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
        m = re.search(r"PICK:\s*(\d+)", text) or re.search(r"\d+", text)
        if m and int(m.group(1) if m.lastindex else m.group(0)) < len(options):
            pick = options[int(m.group(1) if m.lastindex else m.group(0))]
            why = re.search(r"WHY:\s*(.+)", text)
            print(f"    Claude picked '{pick.get('title')}'" + (f" ({why.group(1).strip()})" if why else ""))
            return pick
        print(f"    Claude's answer didn't name a song: {text[:80]!r}")
    except Exception as e:  # never block the post over music
        print(f"    Claude couldn't pick a song ({e}); picking from the trending list.")
    return None


def pick_audio(ig_user_id, token, reel_seconds, hook=""):
    """Return an audio dict ({audio_id, title, display_artist, ...}) or None."""
    options = usable(candidates(ig_user_id, token), reel_seconds)[:40]
    if not options:
        print("    no usable trending songs right now; posting without music.")
        return None
    choice = claude_pick(options, hook)
    if choice is None:
        trending = [a for a in options if a["_source"] == "trending"] or options
        choice = random.choice(trending[:10])
    return choice


if __name__ == "__main__":
    tok = os.environ.get("FB_PAGE_TOKEN", "").strip()
    uid = os.environ.get("IG_USER_ID", "").strip()
    if not tok or not uid:
        raise SystemExit("Set FB_PAGE_TOKEN and IG_USER_ID to test.")
    a = pick_audio(uid, tok, 20, "Pull-ups stuck? Check these 4 mistakes")
    print(json.dumps(a, indent=1) if a else "No song picked.")
