#!/usr/bin/env python3
"""
Generate a batch of Instagram carousel posts with the Claude API and add them to posts.csv.

With "auto_approve": true in config.json, new posts go straight into the queue.
With false, they are saved as "draft" until you change status to "approved".

Usage:
    python generate_ideas.py        # uses posts_per_batch from config.json
    python generate_ideas.py 10     # generate 10 posts
"""

import os
import re
import sys
import uuid
from datetime import date

import anthropic

import exercise_db
from insights import performance_notes
from common import CONFIG, SLIDE_SEP, load_posts, save_posts

HISTORY_LIMIT = 80  # past hooks shown to the model so it avoids repeats
MAX_ROUNDS = 4      # how many times to ask for replacements when posts fail the voice check

# Anything matching these gets the post thrown out and rewritten. Case-insensitive.
AI_TELLS = [
    r"—", r"–",                      # em dash, en dash
    r"\bunlock", r"\belevate", r"game[- ]?changer", r"level up", r"dive in(to)?\b",
    r"\bjourney\b", r"crush (it|your)", r"\btransform", r"\bultimate\b",
    r"here'?s the thing", r"let'?s be real", r"it'?s not just", r"whether you'?re",
    r"\bdelve", r"\btapestry", r"\bembark", r"\bharness", r"\bseamless", r"\brobust",
    r"\bin today'?s\b", r"fast[- ]paced world", r"\bboost your", r"\btake .{0,20} to the next level",
    r"\bsupercharge", r"\bgame plan\b", r"\byour fitness goals\b", r"\bbusy lifestyle",
    r"\bimagine\b", r"\bdid you know\b", r"\bthe secret to\b", r"\bfuel your",
]
AI_TELLS_RE = re.compile("|".join(AI_TELLS), re.IGNORECASE)
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


def voice_problems(post):
    """Return a list of reasons this post sounds AI-written (empty list = passes)."""
    problems = []
    text = " ".join([post.get("hook", ""), post.get("caption", "")] + list(post.get("slides", [])))
    for m in AI_TELLS_RE.finditer(text):
        problems.append(f"uses '{m.group(0)}'")
    if len(EMOJI_RE.findall(post.get("caption", ""))) > 1:
        problems.append("more than one emoji in caption")
    if any(EMOJI_RE.search(s) for s in post.get("slides", [])) or EMOJI_RE.search(post.get("hook", "")):
        problems.append("emoji on a slide")
    if text.count("!") > 2:
        problems.append("too many exclamation points")
    return problems

POST_TOOL = {
    "name": "save_posts",
    "description": "Save the batch of Instagram carousel posts.",
    "input_schema": {
        "type": "object",
        "properties": {
            "posts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "hook": {
                            "type": "string",
                            "description": "Cover slide headline. Max 12 words. Must make someone stop scrolling.",
                        },
                        "slides": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 3,
                            "maxItems": 6,
                            "description": "Body slides after the cover. Each max 35 words. One idea per slide.",
                        },
                        "caption": {
                            "type": "string",
                            "description": "Instagram caption, 40-120 words, ends with a question to drive comments.",
                        },
                        "hashtags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 5,
                            "maxItems": 10,
                            "description": "Relevant hashtags without the # symbol.",
                        },
                        "exercises": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Exact names, from the exercise list, of every exercise this post mentions. Empty if none.",
                        },
                    },
                    "required": ["hook", "slides", "caption", "hashtags", "exercises"],
                },
            }
        },
        "required": ["posts"],
    },
}


def build_prompt(count, past_hooks, exercises):
    history = "\n".join(f"- {h}" for h in past_hooks) or "(none yet)"
    return f"""You write Instagram carousel posts for the page "{CONFIG['page_name']}".

Niche: {CONFIG['niche']}
Audience: {CONFIG['audience']}
Tone: {CONFIG['tone']}

Write {count} new carousel posts. Mix these formats across the batch:
- A complete short workout (exercises, sets, reps, rest, total time)
- Common mistakes and the fix
- Myth vs. fact
- A simple habit or scheduling strategy for busy people
- A checklist or "save this" reference

Rules:
- Original, specific, practical advice. No vague motivation filler.
- Workouts must be realistic for 30-45 minutes and safe for healthy beginners to intermediates.
- No medical claims, no supplement or diet-drug promotion, no invented statistics or studies.
- No body shaming, no before/after promises, no "guaranteed results".
- No mentions of brands, products, or sponsors.
- Plain language. No emojis on slides.

Voice (this matters most, the posts must not read like AI wrote them):
- Write like a regular guy who lifts on his lunch break, talking to a coworker. Short, plain, a little casual. Use contractions.
- Mix short and long sentences. Fragments are fine. Not every slide needs a full sentence.
- Have opinions. Say what to skip and why ("skip the cable flyes, you don't have time").
- Never use: em dashes, "unlock", "elevate", "game-changer", "level up", "dive in", "journey",
  "crush it", "transform", "ultimate", "Here's the thing", "Let's be real", "It's not just X, it's Y",
  "Whether you're X or Y", or lists of exactly three adjectives.
- Captions: at most one emoji, no motivational poster lines, no "Save this!" in every caption. Vary how captions end.
- Don't invent personal stories, results, or numbers about yourself or followers.

Exercises: only use exercises from this list (from an open exercise database), and
write their names exactly as shown in the "exercises" field. On slides you may use a
shorter everyday name. Describe how to do them in your own words.
Format: name | equipment | level | category | primary muscles
{exercises}

Do not repeat or closely rephrase any of these previous hooks:
{history}

Call save_posts with the batch."""


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set the ANTHROPIC_API_KEY environment variable first. See README.md.")

    rows = load_posts()
    if len(sys.argv) > 1:
        count = int(sys.argv[1])
    else:
        # Top the queue up to one week's worth instead of piling on extra posts.
        queued = sum(1 for r in rows if r["status"].lower() in ("approved", "rendered", "draft"))
        count = int(CONFIG.get("posts_per_batch", 7)) - queued
        if count <= 0:
            print(f"Queue already has {queued} posts. Nothing to generate this week.")
            return
    past_hooks = [r["hook"] for r in rows][-HISTORY_LIMIT:]

    today = date.today()
    sample = exercise_db.weekly_sample(seed=today.isocalendar()[0] * 100 + today.isocalendar()[1])
    valid_names = exercise_db.known_names()
    print(f"Loaded {len(sample)} exercises from the open exercise database for this batch.")

    client = anthropic.Anthropic()
    exercise_list = exercise_db.format_for_prompt(sample)

    perf = performance_notes()
    if perf:
        print("Using last weeks' performance to guide this batch.")

    def ask(n, hooks_to_avoid, feedback=""):
        prompt = build_prompt(n, hooks_to_avoid, exercise_list) + perf + feedback
        for attempt in range(1, 4):
            response = client.messages.create(
                model=CONFIG.get("model", "claude-sonnet-5-5"),
                max_tokens=16000,
                tools=[POST_TOOL],
                tool_choice={"type": "auto"},
                messages=[{"role": "user", "content": prompt}],
            )
            block = next(
                (b for b in response.content if b.type == "tool_use" and b.name == "save_posts"), None
            )
            if block is not None:
                return block.input.get("posts", [])
        return []

    accepted, rejected_notes = [], []
    for round_no in range(1, MAX_ROUNDS + 1):
        needed = count - len(accepted)
        if needed <= 0:
            break
        feedback = ""
        if rejected_notes:
            feedback = ("\n\nYour last batch had posts that sounded AI-written and were thrown out:\n"
                        + "\n".join(f"- {n}" for n in rejected_notes[-10:])
                        + "\nWrite like a real person. Avoid those patterns completely.")
        print(f"Round {round_no}: asking Claude for {needed} posts...")
        hooks = past_hooks + [p["hook"] for p in accepted]
        for post in ask(needed, hooks[-HISTORY_LIMIT:], feedback):
            unknown = [n for n in post.get("exercises", []) if n.strip().lower() not in valid_names]
            if unknown:
                print(f"  Rejected '{post['hook']}': exercises not in the database: {', '.join(unknown)}")
                continue
            problems = voice_problems(post)
            if problems:
                print(f"  Rejected '{post['hook']}': sounds AI-written ({'; '.join(problems)})")
                rejected_notes.append(f"'{post['hook']}': {'; '.join(problems)}")
                continue
            accepted.append(post)
            if len(accepted) >= count:
                break

    if not accepted:
        sys.exit("No posts passed the checks. Try running again.")

    status = "approved" if CONFIG.get("auto_approve") else "draft"
    new_rows = []
    for post in accepted:
        new_rows.append({
            "id": f"{today:%Y%m%d}-{uuid.uuid4().hex[:4]}",
            "created": today.isoformat(),
            "status": status,
            "hook": post["hook"].strip(),
            "slides": SLIDE_SEP.join(s.strip() for s in post["slides"]),
            "caption": post["caption"].strip(),
            "hashtags": " ".join("#" + t.strip().lstrip("#").replace(" ", "") for t in post["hashtags"]),
            "published_at": "",
            "media_id": "",
        })

    save_posts(rows + new_rows)
    print(f"Added {len(new_rows)} posts to posts.csv as '{status}':")
    for r in new_rows:
        print(f"  [{r['id']}] {r['hook']}")


if __name__ == "__main__":
    main()
