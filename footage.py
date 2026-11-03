#!/usr/bin/env python3
"""
Background workout footage for Reels, from Pexels (free to use, no attribution required:
https://www.pexels.com/license/).

Needs PEXELS_API_KEY. Without it, Reels use the plain dark background like before.
Clips are picked to match what the post is about (kettlebell, push-ups, stretching...),
a different clip for each slide, and cached so a week's renders don't re-download.
"""

import hashlib
import os
import random
import re
from pathlib import Path

import requests

API = "https://api.pexels.com/videos/search"
CACHE = Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "lbl-footage"

# (words in the post, Pexels search) - first match wins; order = most specific first
TOPICS = [
    (r"kettlebell", "kettlebell workout"),
    (r"pull-?ups?|chin-?ups?", "pull up workout"),
    (r"push-?ups?", "push ups"),
    (r"\bsquat", "squat workout"),
    (r"deadlift|\brdl\b", "deadlift"),
    (r"lunge", "lunges workout"),
    (r"\brow\b|rows\b", "dumbbell row"),
    (r"plank|core|\babs?\b|dead bug", "plank exercise"),
    (r"stretch|mobility|hip flexor", "stretching exercise"),
    (r"\bwalk|steps\b", "walking city"),
    (r"band", "resistance band workout"),
    (r"dumbbell", "dumbbell workout"),
    (r"desk|office|meeting|work clothes", "office workout"),
]
FALLBACK = ["gym workout", "weight training", "strength training"]


def queries_for(post):
    text = f"{post.get('hook', '')} {post.get('slides', '')}".lower()
    found = [q for pat, q in TOPICS if re.search(pat, text)]
    return (found[:2] or []) + FALLBACK[:1]


def search(query, key):
    r = requests.get(API, headers={"Authorization": key}, timeout=30,
                     params={"query": query, "orientation": "portrait", "size": "medium", "per_page": 30})
    r.raise_for_status()
    return r.json().get("videos", [])


def best_file(video):
    """Smallest portrait MP4 that's at least 1280 tall (keeps downloads and the repo small)."""
    files = [f for f in video.get("video_files", [])
             if f.get("file_type") == "video/mp4" and (f.get("height") or 0) >= 1280
             and (f.get("height") or 0) > (f.get("width") or 0)]
    return min(files, key=lambda f: f["height"]) if files else None


def download(url):
    CACHE.mkdir(parents=True, exist_ok=True)
    path = CACHE / (hashlib.sha1(url.encode()).hexdigest()[:16] + ".mp4")
    if not path.exists():
        with requests.get(url, stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
    return path


def clips_for(post, count, min_seconds):
    """Return `count` local clip paths (may repeat if few results), or [] if footage isn't available."""
    key = os.environ.get("PEXELS_API_KEY", "").strip()
    if not key:
        return []
    rng = random.Random(post.get("id", ""))
    pool, seen = [], set()
    for q in queries_for(post):
        try:
            vids = search(q, key)
        except Exception as e:
            print(f"    footage search '{q}' failed: {e}")
            continue
        rng.shuffle(vids)
        for v in vids:
            f = best_file(v)
            if f and v["id"] not in seen and (v.get("duration") or 0) >= min_seconds:
                seen.add(v["id"])
                pool.append(f["link"])
        if len(pool) >= count:
            break
    if not pool:
        return []
    out = []
    for i in range(count):
        try:
            out.append(download(pool[i % len(pool)]))
        except Exception as e:
            print(f"    footage download failed: {e}")
            return []
    return out
