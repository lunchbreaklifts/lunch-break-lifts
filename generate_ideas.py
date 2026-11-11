#!/usr/bin/env python3
"""
Generate a batch of Instagram carousel posts with the Claude API and add them to posts.csv.

With "auto_approve": true in config.json, new posts go straight into the queue.
With false, they are saved as "draft" until you change status to "approved".

Usage:
    python generate_ideas.py        # uses posts_per_batch from config.json
    python generate_ideas.py 10     # generate 10 posts
"""

import json
import os
import re
import sys
import uuid
from datetime import date, timedelta

import anthropic

import exercise_db
from insights import performance_notes, style_mix
from common import CONFIG, ROOT, SLIDE_SEP, load_posts, save_posts

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
    if post.get("style") == "loop":
        if len(post.get("slides", [])) != 1:
            problems.append("loop posts have exactly 1 slide (the punchline)")
        elif len(f"{post.get('hook', '')} {post['slides'][0]}".split()) > 16:
            problems.append("loop over 16 words total (it must read in 3 seconds)")
        if post.get("part2"):
            problems.append("loop posts can't be a series")
    limit = 18 if post.get("style") == "workout" else 12
    if any(len(sl.split()) > limit + 3 for sl in post.get("slides", [])):
        problems.append(f"slide over {limit} words (Reels must read in a glance)")
    if len(post.get("hook", "").split()) > (12 if post.get("style") == "workout" else 9):
        problems.append("hook too long")
    own = CONFIG.get("handle", "").lstrip("@").lower()
    if any(m.lower() != own for m in re.findall(r"@([A-Za-z0-9_.]+)", text)):
        problems.append("tags or names someone (posts never name followers)")
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
                            "minItems": 1,
                            "maxItems": 4,
                            "description": "Body slides after the cover. loop: exactly 1 slide (the punchline). quick tip / relatable: 1-2 slides, max 12 words each. workout: 2-4 slides, max 18 words each. One idea per slide, readable in a glance.",
                        },
                        "caption": {
                            "type": "string",
                            "description": "Instagram caption, 40-120 words. First line is a natural search phrase (see rules). Ends with a question to drive comments.",
                        },
                        "hashtags": {
                            "type": "array",
                            "items": {"type": "string"},
                            "minItems": 3,
                            "maxItems": 5,
                            "description": "3-5 relevant hashtags without the # symbol (Instagram allows 5 at most).",
                        },
                        "exercises": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Exact names, from the exercise list, of every exercise this post mentions. Empty if none.",
                        },
                        "part2": {
                            "type": "object",
                            "description": "Only for 2-part series posts: the second part, which goes out as the very next post.",
                            "properties": {
                                "hook": {"type": "string", "description": "Starts with 'Part 2:'. Max 9 words."},
                                "slides": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 3},
                                "caption": {"type": "string"},
                            },
                            "required": ["hook", "slides", "caption"],
                        },
                        "style": {
                            "type": "string",
                            "enum": ["loop", "quick tip", "relatable", "workout"],
                            "description": "Which format this post is (see the mix in the instructions).",
                        },
                        "reply_to": {
                            "type": "string",
                            "description": "Only for posts answering a follower question: the word follower. Otherwise empty.",
                        },
                    },
                    "required": ["hook", "slides", "caption", "hashtags", "exercises", "style"],
                },
            }
        },
        "required": ["posts"],
    },
}


JUDGE_TOOL = {
    "name": "score_posts",
    "description": "Score each candidate post.",
    "input_schema": {
        "type": "object",
        "properties": {"scores": {"type": "array", "items": {"type": "object", "properties": {
            "index": {"type": "integer"},
            "score": {"type": "integer", "minimum": 1, "maximum": 10},
            "why": {"type": "string", "description": "Under 12 words."}},
            "required": ["index", "score"]}}},
        "required": ["scores"],
    },
}


def judge(client, model, posts):
    """Have a strict editor score candidates; returns a score per post (5 if judging fails)."""
    listing = "\n\n".join(
        f"[{i}] ({p.get('style', '')}) HOOK: {p['hook']}\nSLIDES: " + " / ".join(p.get("slides", []))
        + f"\nCAPTION START: {p.get('caption', '')[:160]}" for i, p in enumerate(posts))
    prompt = f"""You're the toughest editor at a fitness Reels page for busy office workers. Each post
below becomes a 5-10 second Reel. Score each 1-10 on how likely a stranger scrolling at lunch is to
STOP, WATCH TO THE END, and SAVE or SEND it. Judge: does the hook land in one second, can every
slide be read at a glance, is it specific and genuinely useful or genuinely funny, does it sound
like a real person (not AI, not a fitness cliche), and would someone send it to a coworker.
Be harsh: most posts are a 5 or 6. Only a post you'd bet on gets an 8+.

{listing}

Call score_posts with a score for every post."""
    try:
        resp = client.messages.create(model=model, max_tokens=6000, tools=[JUDGE_TOOL],
                                      tool_choice={"type": "auto"},
                                      messages=[{"role": "user", "content": prompt}])
        block = next((b for b in resp.content if b.type == "tool_use"), None)
        got = {int(s["index"]): int(s["score"]) for s in (block.input.get("scores", []) if block else [])}
    except Exception as e:
        print(f"  editor pass skipped ({e})")
        got = {}
    return [got.get(i, 5) for i in range(len(posts))]


def build_prompt(count, past_hooks, exercises, questions=None, window="", mix=None):
    mix = mix or {"loop": 30, "quick tip": 25, "relatable": 25, "workout": 20}
    history = "\n".join(f"- {h}" for h in past_hooks) or "(none yet)"
    extra = ""
    if window:
        extra += f"""
Timing: these posts go out {window}. Where it fits naturally, use the season or calendar
(a holiday week, cold or dark weather, year-end busy season, New Year). Don't force it.

Angles bigger accounts ignore (use a few across the batch): working out in work clothes,
no-sweat lunch workouts, stretches between meetings, hotel-room workouts for work trips,
fitting it around a 9/80 or shift schedule, getting back after a sick week.
"""
    if questions:
        qs = "\n".join(f"- \"{q['comment']}\"" for q in questions)
        extra += f"""
Real follower questions from the comments (answer each one with its own post):
{qs}
For these posts: hook starts with "A follower asked:" followed by a short, general version of
the question (no names, no personal details); slides give the answer; caption thanks
"whoever asked this in the comments" naturally, without naming anyone. Set reply_to to
"follower". Only answer if it's a normal fitness question; skip anything about pain,
injury, or medical issues.
"""
    lead = CONFIG.get("lead_magnet", {})
    if lead.get("enabled"):
        extra += f"""
About a third of captions (mostly workout posts) can mention commenting {lead['keyword']} for the free
30-day lunch break plan, placed before the closing question. Vary the wording.
"""
    return f"""You write Instagram carousel posts for the page "{CONFIG['page_name']}".

Niche: {CONFIG['niche']}
Audience: {CONFIG['audience']}
Tone: {CONFIG['tone']}

Write {count} new posts. They go out as short Reels, and people decide in about one second
whether to keep watching. Data from this page: viewers scroll past long, text-heavy videos.
So every post is SHORT: a hook plus 1-4 slides, readable at a glance, total 6-12 seconds.

Use this mix across the batch (set "style" on each):
- About {mix.get("loop", 0)}% "loop": a 5-second Reel that plays on repeat. Hook = the setup, exactly 1 slide =
  the punchline, 16 words total at most. It must be funnier or truer the second time, so people
  watch it twice and send it to someone. Relatable desk-job and lunch-workout moments work best.
  Examples: hook "Me telling my boss I'm grabbing lunch" / slide "The lunch: 4 sets of rows."
  Hook "11:59 calendar check" / slide "Nobody book me. I'm benching." No advice, no "save this".
- About {mix["quick tip"]}% "quick tip": hook + 1-2 slides. One specific, useful thing (a form fix, a swap,
  a time saver). Example: hook "Your rows are all arms" / slide "Pull your elbow to your back pocket."
- About {mix["relatable"]}% "relatable": hook + 1-2 slides. The funny, true side of working out on a lunch
  break or at a desk job, the kind of thing people send to a coworker. Example: hook
  "Me at 11:58 pretending to finish an email" / slide "Gym bag already in the car." Light,
  never mean, never about bodies. Caption invites them to tag or send it to a work friend.
- About {mix["workout"]}% "workout": hook + 2-4 slides. A complete short workout or "save this" reference,
  tight: exercise, sets x reps on one line each.

Hooks: max 8 words for loop, quick tip and relatable, max 12 for workout. Make them land in one second.
Hook patterns that hold viewers (vary them): a specific situation plus a time limit ("Only 20
minutes today?"), a warning ("Stop doing rows like this"), a number ("The 1 reason your back feels
tight at 3pm"), myth vs fact ("Sweaty doesn't mean it worked"), or a relatable moment
("Me at 11:58 pretending to finish an email"). Pay off the hook in the very first slide; don't make
people wait.

Series (exactly 1 or 2 posts in this batch): split one idea into 2 parts. Part 1 is a normal post
whose hook ends with "(part 1)" and whose last slide sets up what's next without giving it away.
Put part 2 in "part2" (its hook starts "Part 2:"). Part 2 goes out right after part 1, so people
who liked part 1 follow to catch it. Good series: "3 desk stretches (part 1)" then "Part 2: the
2 that fix your lower back".

Search (Instagram search works like Google now):
- The FIRST LINE of every caption must read naturally AND contain a phrase people actually
  type into search, e.g. "30 minute dumbbell workout", "lunch break workout", "workout at
  work", "quick upper body workout", "beginner kettlebell workout", "desk job back pain
  stretches". Write it like a person would, not a keyword list. Vary the phrase per post.
- Hashtags: 3-5 only (Instagram's limit is 5): 1 broad (#workout), 2 mid (#lunchbreakworkout), 1-2 specific to the post.

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
- Captions: at most one emoji, no motivational poster lines, no "Save this!" in every caption.
- Every caption ends with ONE easy question people can answer in a word or two (an either/or,
  "what time do you train?", "what's your go-to excuse?"). Vary them. Comments push Reels further.
- Don't invent personal stories, results, or numbers about yourself or followers.

Exercises: only use exercises from this list (from an open exercise database), and
write their names exactly as shown in the "exercises" field. On slides you may use a
shorter everyday name. Describe how to do them in your own words.
Format: name | equipment | level | category | primary muscles
{exercises}

{extra}
Do not repeat or closely rephrase any of these previous hooks:
{history}

Call save_posts with the batch."""


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set the ANTHROPIC_API_KEY environment variable first. See README.md.")

    rows = load_posts()
    if "--fresh" in sys.argv:
        # Replace queued regular posts with new ones (challenge posts and re-posts stay).
        retired = 0
        for r in rows:
            if (r["status"].lower() in ("approved", "rendered", "draft") and not r.get("challenge_date")
                    and not r.get("repost_of")):
                r["status"] = "retired"
                retired += 1
        save_posts(rows)
        sys.argv.remove("--fresh")
        print(f"Retired {retired} queued posts; writing a fresh batch.")
    if len(sys.argv) > 1:
        count = int(sys.argv[1])
    else:
        # Top the queue up to one week's worth instead of piling on extra posts.
        queued = sum(1 for r in rows if r["status"].lower() in ("approved", "rendered", "draft")
                     and not r.get("challenge_date"))
        target = int(CONFIG.get("posts_per_batch", 7)) - len(upcoming_challenge_days(rows, date.today()))
        count = target - queued
        if count <= 0:
            print(f"Queue already has {queued} regular posts. No new regular posts this week.")
            add_challenge_posts(rows)
            add_reposts()
            return
    past_hooks = [r["hook"] for r in rows][-HISTORY_LIMIT:]

    today = date.today()
    sample = exercise_db.weekly_sample(seed=today.isocalendar()[0] * 100 + today.isocalendar()[1])
    valid_names = exercise_db.known_names()
    print(f"Loaded {len(sample)} exercises from the open exercise database for this batch.")

    client = anthropic.Anthropic()
    exercise_list = exercise_db.format_for_prompt(sample)

    writer = CONFIG.get("writer_model") or CONFIG.get("model", "claude-sonnet-5-5")
    mix, tuned = style_mix()
    print(f"Style mix this week: {mix}" + (" (tuned from watch time)" if tuned else " (default until there's data)"))
    perf = performance_notes()
    if perf:
        print("Using last weeks' performance to guide this batch.")

    questions = follower_questions()
    if questions:
        print(f"Including {len(questions)} real follower question(s).")
    window = f"between {today + timedelta(days=1):%B %-d} and {today + timedelta(days=8):%B %-d, %Y}"

    def ask(n, hooks_to_avoid, feedback=""):
        prompt = build_prompt(n, hooks_to_avoid, exercise_list, questions, window, mix) + perf + feedback
        for attempt in range(1, 4):
            response = client.messages.create(
                model=writer,
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

    final_count = count
    count = min(count * 2, count + 12)  # write extra candidates; the editor keeps the best
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
    if len(accepted) > final_count:
        scores = judge(client, writer, accepted)
        ranked = sorted(zip(scores, range(len(accepted))), key=lambda t: (-t[0], t[1]))
        keep = sorted(i for _, i in ranked[:final_count])
        for sc, i in ranked[final_count:]:
            print(f"  Editor cut ({sc}/10): {accepted[i]['hook']}")
        print(f"Editor kept {final_count} of {len(accepted)} (scores {sorted(scores, reverse=True)[:final_count]})")
        accepted = [accepted[i] for i in keep]

    status = "approved" if CONFIG.get("auto_approve") else "draft"
    new_rows = []
    for post in accepted:
        part2 = post.get("part2") or {}
        series = "series" if part2.get("hook") and part2.get("slides") else ""
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
            "reply_to": (post.get("reply_to") or "").strip().lstrip("@"),
            "style": post.get("style", ""),
            "series": "part1" if series else "",
        })
        if series:
            new_rows.append({
                "id": f"{today:%Y%m%d}-{uuid.uuid4().hex[:4]}",
                "created": today.isoformat(),
                "status": status,
                "hook": part2["hook"].strip(),
                "slides": SLIDE_SEP.join(s.strip() for s in part2["slides"]),
                "caption": part2.get("caption", "").strip() or post["caption"].strip(),
                "hashtags": new_rows[-1]["hashtags"],
                "published_at": "",
                "media_id": "",
                "reply_to": "",
                "style": post.get("style", ""),
                "series": "part2",
            })

    if any(r["reply_to"] for r in new_rows):
        mark_featured(questions)
    save_posts(rows + new_rows)
    print(f"Added {len(new_rows)} posts to posts.csv as '{status}':")
    for r in new_rows:
        print(f"  [{r['id']}] {r['hook']}")
    add_challenge_posts(rows + new_rows)
    add_reposts()


# ---------------------------------------------------------------- follower questions
FEATURED = ROOT / "featured.json"


def follower_questions(limit=2):
    """Recent normal questions from comments, not yet answered in a post. The text is read live
    from Instagram by comment ID (the public repo never stores it), and posts answer them
    anonymously ("A follower asked"), so nobody is named or tagged without asking."""
    try:
        log = json.loads((ROOT / "engage_state.json").read_text(encoding="utf-8")).get("log", [])
    except (FileNotFoundError, ValueError):
        return []
    try:
        done = set(json.loads(FEATURED.read_text(encoding="utf-8")))
    except (FileNotFoundError, ValueError):
        done = set()
    token = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if not token:
        return []
    import requests
    api = f"https://graph.instagram.com/{CONFIG.get('instagram_api_version', 'v23.0')}"
    out, seen = [], set()
    for e in reversed(log):
        cid = e.get("cid")
        if not cid or not e.get("question") or e.get("needs_human") or cid in done or e.get("who") in seen:
            continue
        try:
            text = requests.get(f"{api}/{cid}", params={"fields": "text", "access_token": token},
                                timeout=30).json().get("text", "").strip()
        except Exception:
            continue
        if not text:  # deleted comment: respect that
            continue
        seen.add(e.get("who"))
        out.append({"key": cid, "comment": text[:200]})
        if len(out) >= limit:
            break
    return out


def mark_featured(questions):
    if not questions:
        return
    try:
        done = json.loads(FEATURED.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        done = []
    done += [q["key"] for q in questions]
    FEATURED.write_text(json.dumps(done[-500:], indent=1), encoding="utf-8")


# ---------------------------------------------------------------- 30-day challenge
def challenge_plan():
    try:
        return json.loads((ROOT / "challenge.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return []


def upcoming_challenge_days(rows, today, ahead=8):
    """(day number, date) for challenge days in the next `ahead` days that have no post yet."""
    ch = CONFIG.get("challenge", {})
    if not ch.get("enabled") or not ch.get("start"):
        return []
    start = date.fromisoformat(ch["start"])
    have = {r.get("challenge_date") for r in rows if r.get("challenge_date")}
    out = []
    for i in range(1, ahead + 1):
        d = today + timedelta(days=i)
        n = (d - start).days + 1
        if 1 <= n <= 30 and d.isoformat() not in have:
            out.append((n, d))
    return out


def add_challenge_posts(rows):
    """Write the Day N/30 posts for the coming week from challenge.json."""
    days = upcoming_challenge_days(rows, date.today())
    plan = {d["day"]: d for d in challenge_plan()}
    if not days or not plan:
        return
    client = anthropic.Anthropic()
    lead = CONFIG.get("lead_magnet", {})
    new_rows = []
    for n, when in days:
        info = plan.get(n)
        if not info:
            continue
        prompt = f"""Write one Instagram Reel post for Day {n} of the 30-Day Lunch Break Challenge
on the page "{CONFIG['page_name']}". It goes out {when:%A %B %-d}.

Today's workout ({info['minutes']} min): {info['title']}
{chr(10).join('- ' + b for b in info['blocks'])}
Tip: {info['tip']}

Rules:
- Hook must start exactly with "Day {n}/30:" then a short punchy line (max 12 words total).
- 3 to 5 slides, max 22 words each, giving the workout in plain everyday words so someone can
  follow it from the Reel. Keep the sets/reps from the plan. Use the tip on the last slide.
- Caption 40-100 words. First line contains a natural search phrase (like "30 day workout
  challenge" or "lunch break workout"). Mention people can start any day.
  End with: "Comment {lead.get('keyword', 'LIFT')} and I'll DM you all 30 days."
- 6-9 hashtags including #30daychallenge and #lunchbreakworkout.
- Voice: regular guy who lifts on his lunch break. Contractions. No em dashes, no hype words
  (unlock, elevate, game-changer, level up, journey, crush it, transform, ultimate). At most one
  emoji in the caption, none on slides. No medical claims.
Call save_posts with exactly one post (exercises: empty list)."""
        post = None
        for _ in range(3):
            resp = client.messages.create(
                model=CONFIG.get("model", "claude-sonnet-5-5"), max_tokens=8000,
                tools=[POST_TOOL], tool_choice={"type": "auto"},
                messages=[{"role": "user", "content": prompt}],
            )
            block = next((b for b in resp.content if b.type == "tool_use" and b.name == "save_posts"), None)
            cand = (block.input.get("posts") or [None])[0] if block else None
            if cand and cand["hook"].startswith(f"Day {n}/30") and not voice_problems(cand):
                post = cand
                break
            if cand:
                prompt += f"\n\nLast try was rejected ({'; '.join(voice_problems(cand)) or 'hook format'}). Fix it."
        if not post:
            print(f"  Couldn't write a clean Day {n} post; skipping it.")
            continue
        new_rows.append({
            "id": f"{date.today():%Y%m%d}-d{n:02d}",
            "created": date.today().isoformat(),
            "status": "approved" if CONFIG.get("auto_approve") else "draft",
            "hook": post["hook"].strip(),
            "slides": SLIDE_SEP.join(x.strip() for x in post["slides"]),
            "caption": post["caption"].strip(),
            "hashtags": " ".join("#" + t.strip().lstrip("#").replace(" ", "") for t in post["hashtags"]),
            "published_at": "", "media_id": "",
            "series": "challenge", "challenge_date": when.isoformat(),
        })
        print(f"  [challenge] {when} {post['hook']}")
    if new_rows:
        save_posts(load_posts() + new_rows)


# ---------------------------------------------------------------- re-post winners
def add_reposts(per_week=1, min_age_days=30):
    """Bring back the best Reels after a month with a fresh hook, caption and (at publish) a new song."""
    if not CONFIG.get("reposts", True):
        return
    from insights import load_stats
    from datetime import datetime
    stats = list(load_stats().values())
    rows = load_posts()
    if len(stats) < 6:
        return
    done = {r.get("repost_of") for r in rows if r.get("repost_of")} | {r["id"] for r in rows if r.get("repost_of")}
    views = lambda r: int(r.get("views") or 0)
    avg = sum(views(r) for r in stats) / len(stats)
    by_id = {r["id"]: r for r in rows}
    now = date.today()
    picks = []
    for st in sorted(stats, key=views, reverse=True):
        orig = by_id.get(st["id"])
        if not orig or st["id"] in done or orig.get("series") == "challenge":
            continue
        try:
            age = (now - datetime.fromisoformat(st["published_at"]).date()).days
        except ValueError:
            continue
        if age >= min_age_days and views(st) >= max(100, avg * 1.5):
            picks.append((st, orig))
        if len(picks) >= per_week:
            break
    if not picks:
        return
    client = anthropic.Anthropic()
    lead = CONFIG.get("lead_magnet", {})
    new_rows = []
    for st, orig in picks:
        prompt = f"""This Instagram Reel from "{CONFIG['page_name']}" did well ({views(st)} views). We're posting it
again. Keep the slides exactly, but write a NEW hook and a NEW caption so it feels fresh.

Old hook: {orig['hook']}
Slides: {orig['slides']}
Old caption: {orig['caption']}

Rules: hook max 12 words, different angle from the old one, must stop the scroll. Caption 40-100 words,
first line has a natural search phrase, ends with "Comment {lead.get('keyword', 'LIFT')} and I'll DM you the free 30-day plan."
Voice: regular guy who lifts on his lunch break, contractions, no em dashes, no hype words, at most one emoji.
Call save_posts with exactly one post: copy the slides unchanged, 6-9 hashtags, exercises empty."""
        post = None
        for _ in range(3):
            resp = client.messages.create(model=CONFIG.get("model", "claude-sonnet-5-5"), max_tokens=8000,
                                          tools=[POST_TOOL], tool_choice={"type": "auto"},
                                          messages=[{"role": "user", "content": prompt}])
            block = next((b for b in resp.content if b.type == "tool_use" and b.name == "save_posts"), None)
            cand = (block.input.get("posts") or [None])[0] if block else None
            if cand and cand["hook"].strip().lower() != orig["hook"].strip().lower() and not voice_problems(cand):
                post = cand
                break
        if not post:
            continue
        new_rows.append({
            "id": f"{now:%Y%m%d}-r{uuid.uuid4().hex[:3]}", "created": now.isoformat(),
            "status": "approved" if CONFIG.get("auto_approve") else "draft",
            "hook": post["hook"].strip(), "slides": orig["slides"],
            "caption": post["caption"].strip(),
            "hashtags": " ".join("#" + t.strip().lstrip("#").replace(" ", "") for t in post["hashtags"]),
            "published_at": "", "media_id": "", "repost_of": orig["id"],
        })
        print(f"  [repost] {orig['hook']}  ->  {post['hook']}")
    if new_rows:
        save_posts(rows + new_rows)


if __name__ == "__main__":
    main()
