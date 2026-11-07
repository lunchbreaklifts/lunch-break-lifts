#!/usr/bin/env python3
"""
Render every "approved" post in posts.csv into Instagram carousel images.

Output for each post goes to output/<post id>/:
    slide_01.jpg ... slide_NN.jpg   (1080x1350 JPEG, Instagram's 4:5 portrait size;
                                     the Instagram API only accepts JPEG)
    story.jpg                        (1080x1920 JPEG shared to the Story on posting day)
    caption.txt                      (caption + hashtags, for manual posting)

Rendered posts are marked "rendered" and join the posting queue.
To re-render a post, set its status back to "approved".

Usage:
    python render_slides.py            # render approved posts
    python render_slides.py --stories  # also add story.jpg to queued posts that don't have one
"""

import html
import sys

from playwright.sync_api import sync_playwright

from common import CONFIG, OUTPUT, ROOT, load_posts, save_posts, split_slides
import os

from reel import VERSION as REEL_VERSION, make_footage_reel, make_reel, reading_time, total_seconds
from footage import clips_for

WIDTH, HEIGHT = 1080, 1350
B = CONFIG["brand"]

BASE_CSS = f"""
@import url('https://fonts.googleapis.com/css2?family=Archivo+Black&family=Inter:wght@500;700&display=swap');
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html, body {{ width: {WIDTH}px; height: {HEIGHT}px; background: {B['background']}; color: {B['text']}; }}
body {{ font-family: 'Inter', 'Segoe UI', Arial, sans-serif; display: flex; flex-direction: column; padding: 96px 90px 80px; }}
.top {{ display: flex; justify-content: space-between; align-items: center; font-size: 30px; font-weight: 700; color: {B['muted']}; letter-spacing: 1px; }}
.top .num {{ color: {B['accent']}; }}
.main {{ flex: 1; display: flex; flex-direction: column; justify-content: center; overflow: hidden; }}
.bar {{ width: 120px; height: 14px; background: {B['accent']}; margin-bottom: 48px; }}
.hook {{ font-family: 'Archivo Black', 'Arial Black', sans-serif; font-size: 112px; line-height: 1.04; text-transform: uppercase; }}
.body {{ font-size: 64px; line-height: 1.28; font-weight: 500; white-space: pre-line; }}
.cta {{ font-family: 'Archivo Black', 'Arial Black', sans-serif; font-size: 92px; line-height: 1.08; text-transform: uppercase; }}
.cta-sub {{ font-size: 48px; margin-top: 48px; color: {B['muted']}; font-weight: 500; }}
.cta-sub b {{ color: {B['accent']}; }}
.bottom {{ display: flex; justify-content: space-between; font-size: 30px; font-weight: 700; color: {B['muted']}; }}
.bottom .swipe {{ color: {B['accent']}; }}
"""

# Shrinks the main text until it fits the slide, so long slides never overflow.
FIT_JS = """
() => {
  const main = document.querySelector('.main');
  const el = main.querySelector('.hook, .body, .cta');
  if (!el) return;
  let size = parseFloat(getComputedStyle(el).fontSize);
  while (main.scrollHeight > main.clientHeight && size > 28) {
    size -= 2;
    el.style.fontSize = size + 'px';
  }
}
"""


def page(inner):
    return f"<!doctype html><html><head><meta charset='utf-8'><style>{BASE_CSS}</style></head><body>{inner}</body></html>"


def cover_slide(hook, swipe=True, big=False):
    hint = '<span class="swipe">SWIPE &rarr;</span>' if swipe else "<span></span>"
    size = ' style="font-size:136px"' if big else ""  # Reels: bigger hook for the first second (shrinks to fit)
    return page(f"""
      <div class="top"><span>{html.escape(CONFIG['page_name'].upper())}</span></div>
      <div class="main"><div class="bar"></div><div class="hook"{size}>{html.escape(hook)}</div></div>
      <div class="bottom"><span>{html.escape(CONFIG['handle'])}</span>{hint}</div>
    """)


def body_slide(text, index, total):
    # Short lines get big, bold type so they read in a glance on a phone (shrinks to fit if needed).
    words = len(text.split())
    size = ' style="font-size:100px;font-weight:700;line-height:1.15"' if words <= 10 else (
        ' style="font-size:80px;font-weight:600;line-height:1.2"' if words <= 18 else "")
    return page(f"""
      <div class="top"><span>{html.escape(CONFIG['page_name'].upper())}</span><span class="num">{index:02d}/{total:02d}</span></div>
      <div class="main"><div class="bar"></div><div class="body"{size}>{html.escape(text)}</div></div>
      <div class="bottom"><span>{html.escape(CONFIG['handle'])}</span><span class="swipe">&rarr;</span></div>
    """)


CTA_BY_STYLE = {
    "relatable": "Send this to the coworker who needs it",
    "quick tip": "Save it for your next lunch break",
}


def cta_slide(style="", series=""):
    line = "Follow so you don't miss part 2" if series == "part1" else CTA_BY_STYLE.get(style, CONFIG['cta_line'])
    return page(f"""
      <div class="top"><span>{html.escape(CONFIG['page_name'].upper())}</span></div>
      <div class="main"><div class="bar"></div>
        <div class="cta">{html.escape(line)}</div>
        <div class="cta-sub">Follow <b>{html.escape(CONFIG['handle'])}</b> for more</div>
      </div>
      <div class="bottom"><span>{html.escape(CONFIG['handle'])}</span><span></span></div>
    """)


STORY_W, STORY_H = 1080, 1920

STORY_CSS = BASE_CSS.replace(f"height: {HEIGHT}px", f"height: {STORY_H}px").replace(
    "padding: 96px 90px 80px", "padding: 270px 90px 300px")  # keep clear of Instagram's top and bottom bars
STORY_CSS += f"""
.label {{ display: inline-block; background: {B['accent']}; color: {B['background']}; font-size: 40px;
          font-weight: 700; letter-spacing: 2px; padding: 14px 26px; margin-bottom: 56px; align-self: flex-start; }}
.sub {{ font-size: 48px; margin-top: 56px; color: {B['muted']}; font-weight: 500; }}
.sub b {{ color: {B['accent']}; }}
"""


def story_slide(hook):
    return (f"<!doctype html><html><head><meta charset='utf-8'><style>{STORY_CSS}</style></head><body>"
            f"<div class='top'><span>{html.escape(CONFIG['page_name'].upper())}</span></div>"
            f"<div class='main'><div class='label'>NEW POST</div>"
            f"<div class='hook'>{html.escape(hook)}</div>"
            f"<div class='sub'>It's up on the page now.</div></div>"
            f"<div class='bottom'><span>{html.escape(CONFIG['handle'])}</span><span></span></div>"
            f"</body></html>")


def render_story(browser, row, out_dir):
    tab = browser.new_page(viewport={"width": STORY_W, "height": STORY_H})
    tab.set_content(story_slide(row["hook"]), wait_until="networkidle")
    tab.evaluate(FIT_JS)
    tab.screenshot(path=str(out_dir / "story.jpg"), type="jpeg", quality=92)
    tab.close()


TRANSPARENT = "<style>html,body{background:transparent !important}</style>"


def render_overlays(tab, row, body, total, out_dir):
    """Same slides as the carousel, but with a see-through background, for laying over footage."""
    pages = [cover_slide(row["hook"], swipe=False, big=True)]
    pages += [body_slide(text, i + 2, total) for i, text in enumerate(body)]
    pages.append(cta_slide(row.get("style", ""), row.get("series", "")))
    paths = []
    for i, html_page in enumerate(pages, start=1):
        tab.set_content(html_page.replace("</head>", TRANSPARENT + "</head>"), wait_until="networkidle")
        tab.evaluate(FIT_JS)
        path = out_dir / f"overlay_{i:02d}.png"
        tab.screenshot(path=str(path), type="png", omit_background=True)
        paths.append(path)
    return paths


def refresh_reels(rows):
    """Rebuild queued Reels made in an older style (no browser needed: uses the saved slide images)."""
    for row in rows:
        out_dir = OUTPUT / row["id"]
        if row["status"].lower() != "rendered" or not (out_dir / "reel_cover.jpg").exists():
            continue
        vfile = out_dir / "reel_version.txt"
        if vfile.exists() and vfile.read_text(encoding="utf-8").strip() == REEL_VERSION:
            continue
        body = split_slides(row["slides"])[:8]
        durations = [reading_time(row["hook"], first=True)] + [reading_time(t) for t in body] + [reading_time("", last=True)]
        frames = [out_dir / "reel_cover.jpg"] + sorted(out_dir.glob("slide_*.jpg"))[1:]
        if make_reel(out_dir, frames, durations):
            print(f"  [{row['id']}] Reel rebuilt in the new style ({sum(durations):.0f}s)")


def backfill_stories(browser, rows):
    for row in rows:
        out_dir = OUTPUT / row["id"]
        if row["status"].lower() == "rendered" and out_dir.exists() and not (out_dir / "story.jpg").exists():
            render_story(browser, row, out_dir)
            print(f"  [{row['id']}] added story image")


def main():
    rows = load_posts()
    todo = [r for r in rows if r["status"].lower() == "approved"]
    stories = "--stories" in sys.argv and CONFIG.get("stories", True)
    from footage import available as footage_available
    use_footage = CONFIG.get("reel_footage", True) and footage_available()
    if "--refresh-reels" in sys.argv and CONFIG.get("reels", True):
        if use_footage:
            # queued Reels from before footage existed get fully re-rendered with footage
            for r in rows:
                vfile = OUTPUT / r["id"] / "reel_version.txt"
                if r["status"].lower() == "rendered" and (not vfile.exists() or vfile.read_text().strip() != REEL_VERSION):
                    r["status"] = "approved"
            todo = [r for r in rows if r["status"].lower() == "approved"]
        else:
            refresh_reels(rows)
    if not todo and not stories:
        print('No posts with status "approved". Nothing to render.')
        return

    with sync_playwright() as p:
        browser = p.chromium.launch()
        tab = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})

        for row in todo:
            body = split_slides(row["slides"])[:8]  # cover + 8 + CTA stays within Instagram's carousel limit
            total = len(body) + 2
            slides = [cover_slide(row["hook"])]
            slides += [body_slide(text, i + 2, total) for i, text in enumerate(body)]
            slides.append(cta_slide(row.get("style", ""), row.get("series", "")))

            out_dir = OUTPUT / row["id"]
            out_dir.mkdir(parents=True, exist_ok=True)
            for old in list(out_dir.glob("slide_*")) + list(out_dir.glob("reel*")) + list(out_dir.glob("story*")):
                old.unlink()

            for i, slide_html in enumerate(slides, start=1):
                tab.set_content(slide_html, wait_until="networkidle")
                tab.evaluate(FIT_JS)
                tab.screenshot(path=str(out_dir / f"slide_{i:02d}.jpg"), type="jpeg", quality=92)

            if CONFIG.get("reels", True):
                tab.set_content(cover_slide(row["hook"], swipe=False), wait_until="networkidle")
                tab.evaluate(FIT_JS)
                tab.screenshot(path=str(out_dir / "reel_cover.jpg"), type="jpeg", quality=92)

            if CONFIG.get("stories", True):
                render_story(browser, row, out_dir)

            (out_dir / "caption.txt").write_text(
                f"{row['caption']}\n\n{row['hashtags']}\n", encoding="utf-8"
            )

            reel_note = ""
            if CONFIG.get("reels", True):
                durations = [reading_time(row["hook"], first=True)]
                durations += [reading_time(t) for t in body]
                durations.append(reading_time("", last=True))
                frames = [out_dir / "reel_cover.jpg"] + sorted(out_dir.glob("slide_*.jpg"))[1:]
                made = None
                if use_footage:
                    clips = clips_for(row, len(durations), 3)
                    if clips:
                        overlays = render_overlays(tab, row, body, total, out_dir)
                        made = make_footage_reel(out_dir, overlays, durations, clips)
                        for o in overlays:  # keep the repo small; only the finished video is needed
                            o.unlink(missing_ok=True)
                        if made:
                            reel_note = f" + footage reel ({total_seconds(durations):.0f}s)"
                if not made and make_reel(out_dir, frames, durations):
                    reel_note = f" + reel ({total_seconds(durations):.0f}s)"

            row["status"] = "rendered"
            print(f"  [{row['id']}] {len(slides)} slides{reel_note} -> {out_dir.relative_to(ROOT)}")

        if stories:
            backfill_stories(browser, rows)
        browser.close()

    save_posts(rows)
    print("Done.")


if __name__ == "__main__":
    main()
