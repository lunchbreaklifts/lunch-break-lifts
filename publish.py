#!/usr/bin/env python3
"""
Publish the next queued ("rendered") post to Instagram as a carousel, using the
official Instagram API with Instagram Login (no Facebook Page needed).
Posts at most one post per day.

Needs these environment variables (GitHub secrets when run in Actions):
    IG_USER_ID       Instagram account ID       (from get_token.py)
    IG_ACCESS_TOKEN  Instagram access token      (renewed automatically by refresh_token.py)

Images must be reachable at a public URL. In GitHub Actions this is worked out
automatically from the repo. Running locally, set "image_base_url" in config.json.

Usage:
    python publish.py            # publish the next post
    python publish.py --dry-run  # show what would be published, call nothing
"""

import json
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from common import CONFIG, OUTPUT, ROOT, SLIDE_SEP, load_posts, save_posts

API = f"https://graph.instagram.com/{CONFIG.get('instagram_api_version', 'v23.0')}"
TZ = ZoneInfo(CONFIG.get("timezone", "America/Denver"))
CAPTION_LIMIT = 2200
DRY_RUN = "--dry-run" in sys.argv


def video_base_url():
    """Reels need a host that serves .mp4 as video/mp4. GitHub Pages does; raw links don't."""
    base = CONFIG.get("video_base_url", "").strip()
    if base:
        return base.rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" not in repo:
        return ""
    owner, name = repo.split("/", 1)
    return f"https://{owner.lower()}.github.io/{name}"


def reachable(url, want_type=None):
    try:
        r = requests.head(url, timeout=30, allow_redirects=True)
    except requests.RequestException:
        return False
    if r.status_code != 200:
        return False
    return want_type is None or want_type in r.headers.get("content-type", "")


def image_base_url():
    base = CONFIG.get("image_base_url", "").strip()
    if base:
        return base.rstrip("/")
    repo = os.environ.get("GITHUB_REPOSITORY")
    branch = os.environ.get("GITHUB_REF_NAME", "main")
    if not repo:
        sys.exit('Set "image_base_url" in config.json, or run this from GitHub Actions.')
    return f"https://raw.githubusercontent.com/{repo}/{branch}"


class Instagram:
    def __init__(self, user_id, token, api=API):
        self.user_id = user_id
        self.token = token
        self.api = api

    def call(self, method, path, **params):
        params["access_token"] = self.token
        if method == "POST":
            r = requests.post(f"{self.api}/{path}", data=params, timeout=60)
        else:
            r = requests.get(f"{self.api}/{path}", params=params, timeout=60)
        try:
            data = r.json()
        except ValueError:
            raise RuntimeError(f"Non-JSON response from {path}: HTTP {r.status_code}")
        if r.status_code >= 400 or "error" in data:
            err = data.get("error", data)
            msg = err.get("message", err) if isinstance(err, dict) else err
            raise RuntimeError(f"Instagram API error on {path}: {msg}")
        return data

    def wait_until_ready(self, container_id, label, tries=36):
        for _ in range(tries):  # 5 seconds each
            status = self.call("GET", container_id, fields="status_code").get("status_code")
            if status == "FINISHED":
                return
            if status in ("ERROR", "EXPIRED"):
                raise RuntimeError(f"{label} failed to process (status {status}).")
            time.sleep(5)
        raise RuntimeError(f"Timed out waiting for {label} to process.")

    def publish_reel(self, video_url, caption, cover_url="", audio_id=""):
        params = dict(media_type="REELS", video_url=video_url, caption=caption, share_to_feed="true")
        if cover_url:
            params["cover_url"] = cover_url  # grid thumbnail matches the carousel covers
        if audio_id:
            # Our video's own track is silent, so the song plays at full volume.
            params["audio_configuration"] = json.dumps(
                {"audio_id": audio_id, "audio_volume": 100, "video_volume": 0})
        container = self.call("POST", f"{self.user_id}/media", **params)["id"]
        self.wait_until_ready(container, "reel", tries=90)  # video processing can take a few minutes
        return self.call("POST", f"{self.user_id}/media_publish", creation_id=container)["id"]

    def add_image(self, url, alt):
        """Upload one carousel slide, with alt text for screen readers when Instagram accepts it."""
        if alt:
            try:
                return self.call("POST", f"{self.user_id}/media", image_url=url,
                                 is_carousel_item="true", alt_text=alt[:1000])["id"]
            except RuntimeError as e:
                print(f"    alt text not accepted ({e}); uploading without it.")
        return self.call("POST", f"{self.user_id}/media", image_url=url, is_carousel_item="true")["id"]

    def publish_story(self, image_url):
        container = self.call("POST", f"{self.user_id}/media", media_type="STORIES", image_url=image_url)["id"]
        self.wait_until_ready(container, "story")
        return self.call("POST", f"{self.user_id}/media_publish", creation_id=container)["id"]

    def publish_carousel(self, image_urls, caption, alts=None):
        child_ids = []
        alts = alts or []
        for i, url in enumerate(image_urls, start=1):
            cid = self.add_image(url, alts[i - 1] if i <= len(alts) else "")
            self.wait_until_ready(cid, f"slide {i}")
            child_ids.append(cid)
            print(f"    uploaded slide {i}/{len(image_urls)}")

        carousel_id = self.call(
            "POST", f"{self.user_id}/media",
            media_type="CAROUSEL", children=",".join(child_ids), caption=caption,
        )["id"]
        self.wait_until_ready(carousel_id, "carousel")
        return self.call("POST", f"{self.user_id}/media_publish", creation_id=carousel_id)["id"]


def main():
    if not CONFIG.get("publishing_enabled", True):
        print('Publishing is paused ("publishing_enabled": false in config.json).')
        return

    rows = load_posts()
    today = datetime.now(TZ).date()
    for r in rows:
        if r["published_at"] and datetime.fromisoformat(r["published_at"]).astimezone(TZ).date() == today:
            print(f"Already posted today ([{r['id']}]). Skipping.")
            return

    queue = [r for r in rows if r["status"].lower() == "rendered"]
    if not queue:
        print("Queue is empty. Nothing to publish. The weekly job will add more.")
        return
    post = queue[0]

    slides = sorted((OUTPUT / post["id"]).glob("slide_*.jpg"))
    if len(slides) < 2:
        sys.exit(f"No rendered JPEG slides found for [{post['id']}]. Re-run render_slides.py.")

    base = image_base_url()
    urls = [f"{base}/{s.relative_to(ROOT).as_posix()}" for s in slides]
    caption = f"{post['caption']}\n\n{post['hashtags']}"[:CAPTION_LIMIT]
    alts = alt_texts(post, len(slides))

    published_count = sum(1 for r in rows if r["status"].lower() == "published")
    reel_file = OUTPUT / post["id"] / "reel.mp4"
    # Two Reels for every slideshow: Reels reach new people, slideshows get saved.
    cycle = int(CONFIG.get("reel_cycle", 3))
    want_reel = CONFIG.get("reels", True) and reel_file.exists() and published_count % cycle != cycle - 1
    reel_url = ""
    if want_reel and video_base_url():
        reel_url = f"{video_base_url()}/{reel_file.relative_to(ROOT).as_posix()}"

    fmt = "reel" if reel_url else "carousel"
    print(f"Next post: [{post['id']}] {post['hook']} as a {fmt} ({len(queue) - 1} more in queue)")
    if DRY_RUN:
        print(f"    {reel_url}" if reel_url else "\n".join(f"    {u}" for u in urls))
        print("Dry run: nothing published.")
        return

    if reel_url and not reachable(reel_url, "video/mp4"):
        print(f"    Reel isn't served as video yet ({reel_url}); posting as a carousel instead.")
        reel_url = ""

    if not reachable(urls[0]):
        sys.exit(f"Slide image isn't publicly reachable: {urls[0]}\n"
                 "Make sure the GitHub repo is public and the slides were committed.")

    user_id = os.environ.get("IG_USER_ID", "").strip()
    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if not user_id or not token:
        sys.exit("Set IG_USER_ID and IG_ACCESS_TOKEN first. Run get_token.py to get them.")

    ig = Instagram(user_id, token)
    if reel_url:
        try:
            cover = OUTPUT / post["id"] / "reel_cover.jpg"
            cover_url = f"{base}/{cover.relative_to(ROOT).as_posix()}" if cover.exists() else ""
            try:
                media_id = publish_reel_with_music(user_id, post, reel_url, caption, cover_url)
                if not media_id:
                    media_id = ig.publish_reel(reel_url, caption, cover_url)
            except RuntimeError as e:
                if not cover_url:
                    raise
                print(f"    Reel with custom cover failed ({e}); trying without the cover.")
                media_id = ig.publish_reel(reel_url, caption)
        except RuntimeError as e:
            print(f"    Reel failed ({e}); posting as a carousel instead.")
            media_id = ig.publish_carousel(urls, caption, alts)
    else:
        media_id = ig.publish_carousel(urls, caption, alts)
    post["status"] = "published"
    post["published_at"] = datetime.now(TZ).isoformat(timespec="seconds")
    post["media_id"] = media_id
    post["format"] = "reel" if reel_url else "carousel"
    save_posts(rows)
    print(f"Published as a {'reel' if reel_url else 'carousel'}! Media ID {media_id}")
    share_to_story(ig, post, base)
    if reel_url:
        share_to_facebook(post, reel_url, caption)
        save_posts(rows)  # keep the Facebook ID too
    cleanup_old_media(rows)


def publish_reel_with_music(user_id, post, reel_url, caption, cover_url):
    """Post the Reel with a trending song. Returns the media ID, or None to post it without music."""
    fb_token = os.environ.get("FB_PAGE_TOKEN", "").strip()
    if not fb_token or not CONFIG.get("reel_music", True):
        return None
    try:
        from audio import mark_used, pick_audio
        from reel import reading_time
        body = [t for t in post["slides"].split(SLIDE_SEP) if t.strip()]
        seconds = reading_time("", first=True) + sum(reading_time(t) for t in body) + reading_time("", last=True)
        song = pick_audio(user_id, fb_token, seconds, post["hook"])
        if not song:
            return None
        print(f"    music: {song.get('title')} by {song.get('display_artist')}")
        fb = Instagram(user_id, fb_token, api=f"https://graph.facebook.com/{CONFIG.get('facebook_api_version', 'v23.0')}")
        media_id = fb.publish_reel(reel_url, caption, cover_url, audio_id=song["audio_id"])
    except Exception as e:  # music is a bonus; never lose the post over it
        print(f"    couldn't add music ({e}); posting without it.")
        return None
    try:
        mark_used(song)
    except Exception:
        pass
    post["audio"] = f"{song.get('title')} - {song.get('display_artist')}"
    return media_id


def share_to_facebook(post, reel_url, caption):
    """Also post the Reel on the Facebook Page. Never blocks the Instagram post."""
    token = os.environ.get("FB_PAGE_TOKEN", "").strip()
    if not token or not CONFIG.get("facebook_reels", True):
        return
    try:
        from facebook import share_reel
        vid = share_reel(reel_url, caption, token)
        post["facebook_id"] = vid
        print(f"    shared to Facebook ({vid})")
    except Exception as e:
        print(f"    couldn't share to Facebook ({e}); Instagram post is fine.")


def share_to_story(ig, post, base):
    """Share today's post to the Story too. Never blocks the main post if it fails."""
    if not CONFIG.get("stories", True):
        return
    folder = OUTPUT / post["id"]
    image = folder / "story.jpg"
    if not image.exists():
        image = folder / "slide_01.jpg"  # older posts without a story image: Instagram fits the cover
    url = f"{base}/{image.relative_to(ROOT).as_posix()}"
    try:
        story_id = ig.publish_story(url)
        print(f"    shared to Story ({story_id})")
    except Exception as e:
        print(f"    couldn't share to Story ({e}); the post itself is fine.")


def alt_texts(post, count):
    """Alt text for each slide image: the words on that slide, so screen readers can read it."""
    page = CONFIG.get("page_name", "Lunch Break Lifts")
    body = [t.strip() for t in post["slides"].split(SLIDE_SEP) if t.strip()]
    alts = [f"{page} cover slide: {post['hook']}"]
    alts += [f"Slide {i + 2}: {t}" for i, t in enumerate(body)]
    while len(alts) < count:
        alts.append(f"{page} closing slide: follow {CONFIG.get('handle', '')} for a new lunch break workout every day.")
    return alts[:count]


def cleanup_old_media(rows, keep_days=10):
    """Delete image/video files for posts that went live a while ago, so the repo stays small.
    Instagram keeps its own copy once a post is published. Captions stay in posts.csv."""
    import shutil
    now = datetime.now(TZ)
    for r in rows:
        if r["status"].lower() not in ("published", "skip"):
            continue
        when = r["published_at"] or r["created"]
        try:
            age = (now - datetime.fromisoformat(when).astimezone(TZ)).days
        except ValueError:
            continue
        folder = OUTPUT / r["id"]
        if age >= keep_days and folder.exists():
            shutil.rmtree(folder)
            print(f"    cleaned up old files for [{r['id']}]")


if __name__ == "__main__":
    main()
