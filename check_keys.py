#!/usr/bin/env python3
"""Check that every key works, without posting anything. Never prints the keys."""

import os

import requests

from common import CONFIG


def check(name, fn):
    try:
        print(f"OK   {name}: {fn()}")
        return True
    except Exception as e:
        print(f"FAIL {name}: {e}")
        return False


def ig():
    r = requests.get("https://graph.instagram.com/v23.0/me",
                     params={"fields": "username,followers_count", "access_token": os.environ["IG_ACCESS_TOKEN"]}, timeout=30).json()
    if "error" in r:
        raise RuntimeError(r["error"].get("message"))
    return f"@{r['username']}, {r.get('followers_count')} followers"


def fb_page():
    r = requests.get(f"https://graph.facebook.com/v23.0/{CONFIG['facebook_page_id']}",
                     params={"fields": "name,instagram_business_account", "access_token": os.environ["FB_PAGE_TOKEN"]},
                     timeout=30).json()
    if "error" in r:
        raise RuntimeError(r["error"].get("message"))
    return f"Page '{r['name']}', linked IG {r.get('instagram_business_account', {}).get('id')}"


def music():
    from audio import pick_audio
    song = pick_audio(os.environ["IG_USER_ID"], os.environ["FB_PAGE_TOKEN"], 20, "Pull-ups stuck? Check these 4 mistakes")
    if not song:
        raise RuntimeError("no song found")
    return f"would pick '{song['title']}' by {song['display_artist']}"


def threads():
    if not os.environ.get("THREADS_TOKEN"):
        return "not connected yet (skipped)"
    r = requests.get("https://graph.threads.net/v1.0/me",
                     params={"fields": "username", "access_token": os.environ["THREADS_TOKEN"]}, timeout=30).json()
    if "error" in r:
        raise RuntimeError(r["error"].get("message"))
    return f"@{r['username']}"


if __name__ == "__main__":
    results = [check("Instagram key", ig), check("Facebook Page key", fb_page),
               check("Trending music", music), check("Threads key", threads)]
    print("All good." if all(results) else "Something needs fixing (see FAIL lines).")
