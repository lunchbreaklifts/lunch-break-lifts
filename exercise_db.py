"""
Open exercise data from Free Exercise DB (https://github.com/yuhonas/free-exercise-db),
released into the public domain under the Unlicense.

Only structured facts are used (exercise name, equipment, level, muscles, category).
Instruction text and photos from the dataset are NOT used: Claude writes all post
text in its own words, and the dataset's photos have unclear origins.

The dataset is downloaded once and cached in data/exercises.json.
"""

import json
import random
from pathlib import Path

import requests

from common import CONFIG, ROOT

SOURCE_URL = CONFIG.get(
    "exercise_source_url",
    "https://raw.githubusercontent.com/yuhonas/free-exercise-db/main/dist/exercises.json",
)
CACHE = ROOT / "data" / "exercises.json"
MAX_CACHE_DAYS = 30

DEFAULT_EQUIPMENT = ["body only", "dumbbell", "kettlebells", "bands"]
DEFAULT_LEVELS = ["beginner", "intermediate"]
CATEGORIES = ["strength", "plyometrics", "cardio", "stretching"]


def _download():
    r = requests.get(SOURCE_URL, timeout=60)
    r.raise_for_status()
    data = r.json()
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(data), encoding="utf-8")
    return data


def load_all():
    import time
    if CACHE.exists() and (time.time() - CACHE.stat().st_mtime) < MAX_CACHE_DAYS * 86400:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    try:
        return _download()
    except Exception as e:
        if CACHE.exists():
            print(f"Couldn't refresh exercise data ({e}); using cached copy.")
            return json.loads(CACHE.read_text(encoding="utf-8"))
        raise


def library():
    """Exercises that fit the page: allowed equipment and levels."""
    equipment = set(CONFIG.get("equipment", DEFAULT_EQUIPMENT))
    levels = set(CONFIG.get("levels", DEFAULT_LEVELS))
    return [
        {
            "name": ex["name"],
            "equipment": ex.get("equipment") or "none",
            "level": ex.get("level"),
            "category": ex.get("category"),
            "muscles": ", ".join(ex.get("primaryMuscles") or []),
        }
        for ex in load_all()
        if ex.get("equipment") in equipment
        and ex.get("level") in levels
        and ex.get("category") in CATEGORIES
    ]


def weekly_sample(size=60, seed=None):
    """A varied sample spread across muscle groups, different each week."""
    lib = library()
    rng = random.Random(seed)
    by_muscle = {}
    for ex in lib:
        by_muscle.setdefault(ex["muscles"].split(",")[0] or "other", []).append(ex)
    for group in by_muscle.values():
        rng.shuffle(group)
    sample = []
    while len(sample) < size and any(by_muscle.values()):
        for group in list(by_muscle.values()):
            if group and len(sample) < size:
                sample.append(group.pop())
    return sorted(sample, key=lambda e: (e["category"], e["muscles"], e["name"]))


def known_names():
    return {ex["name"].lower() for ex in library()}


def format_for_prompt(exercises):
    return "\n".join(
        f"- {e['name']} | {e['equipment']} | {e['level']} | {e['category']} | {e['muscles']}"
        for e in exercises
    )
