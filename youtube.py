#!/usr/bin/env python3
"""
YouTube Shorts: upload each Reel to the Lunch Break Lifts YouTube channel.

Needs three secrets (see README, "YouTube Shorts"):
    YT_CLIENT_ID, YT_CLIENT_SECRET   from the Google Cloud OAuth client
    YT_REFRESH_TOKEN                 from the OAuth Playground (youtube.upload scope)

A vertical video under 3 minutes is automatically a Short; there's no separate endpoint.
Never blocks the Instagram post: any problem is printed and skipped.

    python youtube.py --check    # confirm the keys work and show the channel name
"""

import json
import os
import sys

import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"
API = "https://www.googleapis.com/youtube/v3"
TITLE_LIMIT = 100
DESC_LIMIT = 5000


def configured():
    return all(os.environ.get(k, "").strip() for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"))


def access_token():
    r = requests.post(TOKEN_URL, timeout=30, data={
        "client_id": os.environ["YT_CLIENT_ID"].strip(),
        "client_secret": os.environ["YT_CLIENT_SECRET"].strip(),
        "refresh_token": os.environ["YT_REFRESH_TOKEN"].strip(),
        "grant_type": "refresh_token",
    })
    data = r.json()
    if "access_token" not in data:
        raise RuntimeError(f"YouTube key didn't work: {data.get('error_description') or data.get('error') or data}")
    return data["access_token"]


def title_for(post):
    """The hook, plus #Shorts, inside YouTube's 100-character limit. No < or > (YouTube rejects them)."""
    hook = post["hook"].replace("<", "").replace(">", "").strip()
    tag = " #Shorts"
    if len(hook) + len(tag) > TITLE_LIMIT:
        hook = hook[:TITLE_LIMIT - len(tag) - 1].rsplit(" ", 1)[0] + "…"
    return hook + tag


def tags_for(post):
    words = [h.lstrip("#") for h in post.get("hashtags", "").split() if h.startswith("#")]
    out, size = [], 0
    for w in ["lunch break workout", "workout", "fitness"] + words:
        if w.lower() not in (t.lower() for t in out) and size + len(w) < 450:
            out.append(w)
            size += len(w) + 1
    return out


def description_for(caption):
    # YouTube has no comment-keyword DMs, so swap the LIFT invite for where to get the plan.
    text = caption.replace("<", "").replace(">", "")
    text += "\n\nThe free 30-day plan: comment LIFT on any post on Instagram @lunch_breaklifts."
    return text[:DESC_LIMIT]


def upload_short(video_path, post, caption):
    """Upload the Reel file as a public Short. Returns (video_id, privacy) where privacy is what YouTube set."""
    token = access_token()
    meta = {
        "snippet": {
            "title": title_for(post),
            "description": description_for(caption),
            "tags": tags_for(post),
            "categoryId": "17",  # Sports
        },
        "status": {"privacyStatus": "public", "selfDeclaredMadeForKids": False, "embeddable": True},
    }
    size = os.path.getsize(video_path)
    start = requests.post(
        UPLOAD_URL, params={"uploadType": "resumable", "part": "snippet,status"}, timeout=60,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)},
        data=json.dumps(meta))
    if start.status_code >= 400 or "Location" not in start.headers:
        raise RuntimeError(f"YouTube upload start failed: HTTP {start.status_code} {start.text[:300]}")
    with open(video_path, "rb") as f:
        r = requests.put(start.headers["Location"], data=f, timeout=600,
                         headers={"Authorization": f"Bearer {token}", "Content-Type": "video/mp4",
                                  "Content-Length": str(size)})
    if r.status_code >= 400:
        raise RuntimeError(f"YouTube upload failed: HTTP {r.status_code} {r.text[:300]}")
    data = r.json()
    return data["id"], data.get("status", {}).get("privacyStatus", "")


def check():
    if not configured():
        sys.exit("YouTube keys aren't set (YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN).")
    token = access_token()
    r = requests.get(f"{API}/channels", params={"part": "snippet", "mine": "true"}, timeout=30,
                     headers={"Authorization": f"Bearer {token}"}).json()
    items = r.get("items") or []
    if not items:
        sys.exit("The key works, but that Google account has no YouTube channel yet. Create one at "
                 "https://www.youtube.com/create_channel")
    print(f"YouTube OK: channel '{items[0]['snippet']['title']}'")


if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
