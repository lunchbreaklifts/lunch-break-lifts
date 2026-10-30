#!/usr/bin/env python3
"""
Share each Reel to the Lunch Break Lifts Facebook Page too (Reels Publishing API).

Needs FB_PAGE_TOKEN (Page access token with pages_manage_posts) and
"facebook_page_id" in config.json. Never blocks the Instagram post: any problem
is printed and skipped.

Note: Instagram's trending songs can't be carried over to Facebook through the API,
so the Facebook copy plays without music.
"""

import time

import requests

from common import CONFIG

API_VERSION = CONFIG.get("facebook_api_version", "v23.0")
GRAPH = f"https://graph.facebook.com/{API_VERSION}"
RUPLOAD = f"https://rupload.facebook.com/video-upload/{API_VERSION}"


def _check(r, step):
    try:
        data = r.json()
    except ValueError:
        raise RuntimeError(f"{step}: HTTP {r.status_code}")
    if r.status_code >= 400 or "error" in data:
        err = data.get("error", data)
        raise RuntimeError(f"{step}: {err.get('message', err) if isinstance(err, dict) else err}")
    return data


def share_reel(video_url, description, token, page_id=None, wait_tries=60):
    """Upload the hosted MP4 as a Reel on the Page. Returns the Facebook video ID."""
    page_id = page_id or CONFIG.get("facebook_page_id", "")
    if not page_id:
        raise RuntimeError('no "facebook_page_id" in config.json')

    start = _check(requests.post(f"{GRAPH}/{page_id}/video_reels",
                                 json={"upload_phase": "start", "access_token": token}, timeout=60), "start")
    video_id = start["video_id"]

    _check(requests.post(f"{RUPLOAD}/{video_id}",
                         headers={"Authorization": f"OAuth {token}", "file_url": video_url}, timeout=120), "upload")

    for _ in range(wait_tries):  # 5 seconds each
        status = _check(requests.get(f"{GRAPH}/{video_id}",
                                     params={"fields": "status", "access_token": token}, timeout=60), "status")
        state = (status.get("status") or {}).get("video_status", "")
        if state in ("ready", "upload_complete"):
            break
        if state in ("error", "upload_failed", "expired"):
            raise RuntimeError(f"Facebook couldn't process the video ({state})")
        time.sleep(5)

    _check(requests.post(f"{GRAPH}/{page_id}/video_reels", data={
        "video_id": video_id, "upload_phase": "finish", "video_state": "PUBLISHED",
        "description": description[:2200], "access_token": token,
    }, timeout=60), "publish")
    return video_id
