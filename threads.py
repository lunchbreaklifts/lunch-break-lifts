#!/usr/bin/env python3
"""
Threads: post a short version of each day's post, and renew the Threads key.

Needs THREADS_TOKEN (a long-lived Threads user token). Never blocks the Instagram
post: any problem is printed and skipped.

Usage:
    python threads.py --refresh   # print a renewed token (used by the weekly renew job)
"""

import os
import sys
import time

import requests

from common import CONFIG, SLIDE_SEP

API = "https://graph.threads.net/v1.0"
LIMIT = 500  # Threads post length limit


def _call(method, path, token, **params):
    params["access_token"] = token
    if method == "POST":
        r = requests.post(f"{API}/{path}", data=params, timeout=60)
    else:
        r = requests.get(f"{API}/{path}", params=params, timeout=60)
    data = r.json()
    if r.status_code >= 400 or "error" in data:
        err = data.get("error", data)
        raise RuntimeError(err.get("message", err) if isinstance(err, dict) else err)
    return data


def thread_text(post):
    """Hook + the first useful slide or two, written to stand alone on Threads."""
    body = [s.strip() for s in post["slides"].split(SLIDE_SEP) if s.strip()]
    text = post["hook"].strip()
    for s in body[:2]:
        candidate = f"{text}\n\n{s}"
        if len(candidate) > LIMIT - 60:
            break
        text = candidate
    tail = f"\n\nThe rest is on IG: {CONFIG.get('handle', '')}"
    return (text + tail)[:LIMIT]


def post_thread(post, image_url, token):
    """Publish one Threads post with the cover image. Returns the Threads media ID."""
    params = {"media_type": "IMAGE", "image_url": image_url, "text": thread_text(post)}
    try:
        container = _call("POST", "me/threads", token, **params)["id"]
    except RuntimeError:
        params = {"media_type": "TEXT", "text": thread_text(post)}
        container = _call("POST", "me/threads", token, **params)["id"]
    time.sleep(30)  # Threads asks for a short wait before publishing
    return _call("POST", "me/threads_publish", token, creation_id=container)["id"]


def refresh():
    token = os.environ.get("THREADS_TOKEN", "").strip()
    if not token:
        sys.exit("THREADS_TOKEN is not set.")
    r = requests.get("https://graph.threads.net/refresh_access_token",
                     params={"grant_type": "th_refresh_token", "access_token": token}, timeout=60)
    data = r.json()
    if "access_token" not in data:
        sys.exit(f"Threads key renewal failed: {data.get('error', data)}")
    print(f"Threads key renewed; valid for about {int(data.get('expires_in', 0)) // 86400} days.",
          file=sys.stderr)
    print(data["access_token"])


if __name__ == "__main__":
    if "--refresh" in sys.argv:
        refresh()
