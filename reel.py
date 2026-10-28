"""
Turn a post's carousel slides into a vertical Reel (1080x1920 MP4) with ffmpeg.

Each slide is centered on the brand background and shown long enough to read,
with a short crossfade between slides. A silent audio track is included because
Instagram's Reel upload expects one.
"""

import shutil
import subprocess
from pathlib import Path

from common import CONFIG

W, H = 1080, 1920
SLIDE_H = 1350
FADE = 0.4
FPS = 30


def reading_time(text, first=False, last=False):
    if first:
        return 2.5
    if last:
        return 2.0
    words = len(text.split())
    return round(min(6.5, max(2.5, 1.5 + 0.25 * words)), 2)


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
    for img, d in zip(slides, durations):
        cmd += ["-loop", "1", "-t", f"{d + FADE:.2f}", "-i", str(img)]
    total = sum(durations) + FADE
    cmd += ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=r=48000:cl=stereo"]

    parts = []
    for i in range(len(slides)):
        parts.append(
            f"[{i}:v]scale={W}:{SLIDE_H},pad={W}:{H}:0:{pad_y}:color=0x{bg},"
            f"setsar=1,fps={FPS},format=yuv420p[v{i}]"
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
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-profile:v", "high",
        "-pix_fmt", "yuv420p", "-r", str(FPS),
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
        "-shortest", "-movflags", "+faststart",
        str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"    reel failed: {result.stderr.strip()[:300]}")
        return None
    return out_path
