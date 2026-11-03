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


def fb_expiry():
    tok = os.environ["FB_PAGE_TOKEN"]
    r = requests.get("https://graph.facebook.com/v23.0/debug_token",
                     params={"input_token": tok, "access_token": tok}, timeout=30).json()
    if "error" in r:
        raise RuntimeError(r["error"].get("message"))
    d = r.get("data", {})
    exp = d.get("expires_at", 0)
    if not d.get("is_valid"):
        raise RuntimeError("key is not valid")
    if exp:
        from datetime import datetime, timezone
        when = datetime.fromtimestamp(exp, timezone.utc).strftime("%b %d %H:%M UTC")
        raise RuntimeError(f"key EXPIRES {when}; it needs to be a never-expiring Page key")
    from facebook import page_token
    pt = page_token(tok)
    pd = requests.get("https://graph.facebook.com/v23.0/debug_token",
                      params={"input_token": pt, "access_token": pt}, timeout=30).json().get("data", {})
    if pd.get("type") != "PAGE":
        raise RuntimeError("couldn't get a Page key from it")
    if pd.get("expires_at"):
        raise RuntimeError("the Page key it gives expires; the saved key must be the never-expiring one")
    return f"saved key is a {d.get('type')} key that never expires; Page key OK"


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


def youtube_key():
    import youtube
    if not youtube.configured():
        return "not connected yet (skipped)"
    token = youtube.access_token()
    r = requests.get(f"{youtube.API}/channels", params={"part": "snippet", "mine": "true"},
                     headers={"Authorization": f"Bearer {token}"}, timeout=30).json()
    items = r.get("items") or []
    if not items:
        raise RuntimeError("key works, but that Google account has no YouTube channel yet")
    return f"channel '{items[0]['snippet']['title']}'"


def pinterest_key():
    import pinterest
    if not pinterest.configured():
        return "not connected yet (skipped)"
    token = pinterest.access_token()
    user = pinterest._call("GET", "user_account", token)
    return f"@{user.get('username')}"


if __name__ == "__main__":
    results = [check("Instagram key", ig), check("Facebook Page key", fb_page),
               check("Facebook key lifetime", fb_expiry),
               check("Trending music", music), check("Threads key", threads),
               check("YouTube key", youtube_key), check("Pinterest key", pinterest_key)]
    print("All good." if all(results) else "Something needs fixing (see FAIL lines).")
