"""
Turn a post's carousel slides into a vertical Reel (1080x1920 MP4) with ffmpeg.

Built for watch time:
  - the hook slide shows for well under 2 seconds,
  - every slide has a slow zoom (alternating in/out) so it never looks like a static slideshow,
  - short crossfades, and each slide only stays up as long as it takes to read.
A silent audio track is included because Instagram's Reel upload expects one; the
trending song is attached by Instagram at publish time.
"""

import shutil
import subprocess
from pathlib import Path

from common import CONFIG

W, H = 1080, 1920
SLIDE_H = 1350
FADE = 0.3
FPS = 30
ZOOM = 0.07  # how far each slide zooms over its time on screen (7%)
VERSION = "2"  # bump to re-render queued Reels with a new style


def reading_time(text, first=False, last=False):
    if first:
        return 1.6
    if last:
        return 1.6
    words = len(text.split())
    return round(min(4.0, max(1.8, 0.9 + 0.11 * words)), 2)


def make_reel(out_dir: Path, slides, durations):
    """Build out_dir/reel.mp4 from the given slide images. Returns the path, or None if skipped."""
    if not shutil.which("ffmpeg"):
        print("    ffmpeg not found, skipping reel")
        return None
    slides = list(slides)
    if len(slides) < 2 or len(slides) != len(durations):
        print("    slide/duration mismatch, skipping reel")
        return None

    bg = CONFIG["brand"]["background"].lstrip("#")
    pad_y = (H - SLIDE_H) // 2
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for img in slides:
        cmd += ["-i", str(img)]
    total = sum(durations) + FADE
    cmd += ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=r=48000:cl=stereo"]

    parts = []
    for i, d in enumerate(durations):
        frames = int(round((d + FADE) * FPS))
        step = ZOOM / max(frames, 1)
        if i % 2 == 0:  # zoom in
            z = f"1+{step:.6f}*on"
        else:           # zoom out
            z = f"{1 + ZOOM:.4f}-{step:.6f}*on"
        parts.append(
            f"[{i}:v]scale={W * 2}:{SLIDE_H * 2},"
            f"zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={W}x{SLIDE_H}:fps={FPS},"
            f"pad={W}:{H}:0:{pad_y}:color=0x{bg},setsar=1,format=yuv420p[v{i}]"
        )
    prev, offset = "v0", 0.0
    for i in range(1, len(slides)):
        offset += durations[i - 1]
        out = f"x{i}"
        parts.append(f"[{prev}][v{i}]xfade=transition=fade:duration={FADE}:offset={offset:.2f}[{out}]")
        prev = out

    out_path = out_dir / "reel.mp4"
    cmd += [
        "-filter_complex", ";".join(parts),
        "-map", f"[{prev}]", "-map", f"{len(slides)}:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-profile:v", "high",
        "-pix_fmt", "yuv420p", "-r", str(FPS), "-g", str(FPS * 2),
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
        "-shortest", "-movflags", "+faststart",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"    reel failed: {result.stderr.strip()[:300]}")
        return None
    (out_dir / "reel_version.txt").write_text(VERSION, encoding="utf-8")
    return out_path
