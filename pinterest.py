#!/usr/bin/env python3
"""
Pinterest: post each Reel as a video Pin (or the cover slide as an image Pin) to a
"Lunch Break Workouts" board.

Needs (see README, "Pinterest"):
    PINTEREST_APP_ID, PINTEREST_APP_SECRET   from the Pinterest developer app
    PINTEREST_REFRESH_TOKEN                  from the app's OAuth flow (valid 1 year;
                                             the Wednesday renew job keeps it current)

Until Pinterest upgrades the app from Trial to Standard access, Pins it creates are only
visible to the account owner. Never blocks the Instagram post.

    python pinterest.py --check     # confirm the keys work, show the board
    python pinterest.py --refresh   # print a renewed refresh token if Pinterest issued one
"""

import base64
import os
import sys
import time

import requests

from common import CONFIG

API = "https://api.pinterest.com/v5"
BOARD_NAME = "Lunch Break Workouts"
BOARD_DESC = "Workouts that fit in a lunch break. 30-45 minutes, dumbbells or nothing."


def configured():
    return all(os.environ.get(k, "").strip()
               for k in ("PINTEREST_APP_ID", "PINTEREST_APP_SECRET", "PINTEREST_REFRESH_TOKEN"))


def _token_call():
    creds = f"{os.environ['PINTEREST_APP_ID'].strip()}:{os.environ['PINTEREST_APP_SECRET'].strip()}"
    r = requests.post(f"{API}/oauth/token", timeout=30,
                      headers={"Authorization": "Basic " + base64.b64encode(creds.encode()).decode()},
                      data={"grant_type": "refresh_token",
                            "refresh_token": os.environ["PINTEREST_REFRESH_TOKEN"].strip()})
    data = r.json()
    if "access_token" not in data:
        raise RuntimeError(f"Pinterest key didn't work: {data.get('message') or data}")
    return data


def access_token():
    return _token_call()["access_token"]


def _call(method, path, token, **kw):
    r = requests.request(method, f"{API}/{path}", timeout=60,
                         headers={"Authorization": f"Bearer {token}"}, **kw)
    data = r.json() if r.content else {}
    if r.status_code >= 400:
        raise RuntimeError(f"Pinterest {path}: HTTP {r.status_code} {data.get('message') or data}")
    return data


def board_id(token):
    data = _call("GET", "boards", token, params={"page_size": 100})
    for b in data.get("items", []):
        if b.get("name", "").lower() == BOARD_NAME.lower():
            return b["id"]
    return _call("POST", "boards", token, json={"name": BOARD_NAME, "description": BOARD_DESC,
                                                 "privacy": "PUBLIC"})["id"]


def upload_video(token, path):
    reg = _call("POST", "media", token, json={"media_type": "video"})
    with open(path, "rb") as f:
        r = requests.post(reg["upload_url"], data=reg["upload_parameters"], files={"file": f}, timeout=600)
    if r.status_code >= 300:
        raise RuntimeError(f"Pinterest video upload failed: HTTP {r.status_code}")
    for _ in range(60):  # up to 5 minutes
        status = _call("GET", f"media/{reg['media_id']}", token).get("status")
        if status == "succeeded":
            return reg["media_id"]
        if status == "failed":
            raise RuntimeError("Pinterest couldn't process the video.")
        time.sleep(5)
    raise RuntimeError("Pinterest video processing timed out.")


def pin_text(post):
    title = post["hook"].strip()[:100]
    desc = post["caption"].split("\n\n")[0].strip()
    tags = " ".join(post.get("hashtags", "").split()[:5])
    desc = f"{desc}\n\nFree 30-day lunch break plan at the link. {tags}".strip()
    return title, desc[:500]


def post_pin(post, cover_url, video_path=None):
    """Create the Pin. Returns its ID."""
    token = access_token()
    title, desc = pin_text(post)
    body = {"board_id": board_id(token), "title": title, "description": desc,
            "alt_text": post["hook"][:500]}
    link = CONFIG.get("lead_magnet", {}).get("url", "")
    if link:
        body["link"] = link
    if video_path and os.path.exists(video_path):
        media_id = upload_video(token, video_path)
        body["media_source"] = {"source_type": "video_id", "media_id": media_id, "cover_image_url": cover_url}
    else:
        body["media_source"] = {"source_type": "image_url", "url": cover_url}
    return _call("POST", "pins", token, json=body)["id"]


def check():
    if not configured():
        sys.exit("Pinterest keys aren't set.")
    token = access_token()
    user = _call("GET", "user_account", token)
    print(f"Pinterest OK: @{user.get('username')}, board id {board_id(token)}")


def refresh():
    """Print a new refresh token if Pinterest rotated it (nothing otherwise)."""
    data = _token_call()
    new = data.get("refresh_token")
    if new and new != os.environ["PINTEREST_REFRESH_TOKEN"].strip():
        print(new)


if __name__ == "__main__":
    if "--check" in sys.argv:
        check()
    elif "--refresh" in sys.argv:
        refresh()
