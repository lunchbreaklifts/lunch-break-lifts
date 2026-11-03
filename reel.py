"""
Turn a post's carousel slides into a vertical Reel (1080x1920 MP4) with ffmpeg.

Built for watch time:
  - the hook slide shows for well under 2 seconds,
  - every slide has a slow zoom (alternating in/out) so it never looks like a static slideshow,
  - short crossfades, and each slide only stays up as long as it takes to read,
  - the first half second "punches in" (starts zoomed, snaps to normal) to stop the scroll,
  - the video ends by fading back into the hook, zooming the way the start does, so the
    replay loops without a visible jump (replays count heavily for Reach).
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
VERSION = "5"  # footage style; bump to re-render queued Reels
PLAIN_VERSION = "3"
PUNCH = 0.08   # first frame starts 8% zoomed in
PUNCH_T = 0.4  # ...and settles to normal over this many seconds
LOOP = 0.6     # seconds of hook at the end, so the replay is seamless


def total_seconds(durations):
    return sum(durations) + LOOP + FADE


def _zoom(label_in, label_out, z):
    # zoompan with d=1 on video = a per-frame centered zoom that keeps the frame size fixed
    return (f"[{label_in}]zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:"
            f"s={W}x{H}:fps={FPS},setsar=1[{label_out}]")


def punch_in(label_in, label_out):
    """Zoomed in at the first frame, back to normal by PUNCH_T."""
    return _zoom(label_in, label_out, f"1+{PUNCH}*max(0,1-it/{PUNCH_T})")


def zoom_to_loop(label_in, label_out):
    """Ends at the same zoom the video starts with, so the loop point matches."""
    return _zoom(label_in, label_out, f"1+{PUNCH}*min(1,it/{LOOP})")


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
    slides = slides + [slides[0]]
    durations = list(durations) + [LOOP]

    bg = CONFIG["brand"]["background"].lstrip("#")
    pad_y = (H - SLIDE_H) // 2
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for img in slides:
        cmd += ["-i", str(img)]
    total = sum(durations) + FADE
    cmd += ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=r=48000:cl=stereo"]

    parts = []
    last = len(durations) - 1
    for i, d in enumerate(durations):
        frames = int(round((d + FADE) * FPS))
        step = ZOOM / max(frames, 1)
        if i % 2 == 0:  # zoom in
            z = f"1+{step:.6f}*on"
        else:           # zoom out
            z = f"{1 + ZOOM:.4f}-{step:.6f}*on"
        if i == 0:      # punch in: start zoomed, snap back in the first fraction of a second
            pf = int(PUNCH_T * FPS)
            z = f"if(lt(on,{pf}),{1 + PUNCH:.4f}-{PUNCH / pf:.6f}*on,1+{step:.6f}*(on-{pf}))"
        elif i == last:  # loop: ease back up to the starting zoom
            z = f"1+{PUNCH / max(frames, 1):.6f}*on"
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
    (out_dir / "reel_version.txt").write_text(PLAIN_VERSION, encoding="utf-8")
    return out_path


def make_footage_reel(out_dir: Path, overlays, durations, clips):
    """Reel with real workout footage behind the text: each slide's text (transparent PNG) sits on a
    darkened clip, with short crossfades between slides. Returns the path, or None on failure."""
    if not shutil.which("ffmpeg") or len(overlays) != len(durations) or len(clips) < len(durations):
        return None
    pad_y = (H - SLIDE_H) // 2
    overlays = list(overlays) + [overlays[0]]
    clips = list(clips[:len(durations)]) + [clips[0]]
    durations = list(durations) + [LOOP]
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for clip, d in zip(clips, durations):
        cmd += ["-stream_loop", "-1", "-t", f"{d + FADE:.2f}", "-i", str(clip)]
    for img in overlays:
        cmd += ["-loop", "1", "-t", "60", "-i", str(img)]
    total = sum(durations) + FADE
    n = len(durations)
    cmd += ["-f", "lavfi", "-t", f"{total:.2f}", "-i", "anullsrc=r=48000:cl=stereo"]

    parts = []
    for i, d in enumerate(durations):
        parts.append(
            f"[{i}:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},"
            f"eq=saturation=0.8,drawbox=x=0:y=0:w=iw:h=ih:color=black@0.62:t=fill,"
            f"trim=duration={d + FADE:.2f},setpts=PTS-STARTPTS,setsar=1[bg{i}]"
        )
        parts.append(f"[{n + i}:v]format=rgba,scale={W}:{SLIDE_H}[tx{i}]")
        parts.append(f"[bg{i}][tx{i}]overlay=0:{pad_y}:shortest=1,format=yuv420p[c{i}]")
        if i == 0:
            parts.append(punch_in(f"c{i}", f"v{i}"))
        elif i == n - 1:
            parts.append(zoom_to_loop(f"c{i}", f"v{i}"))
        else:
            parts.append(f"[c{i}]null[v{i}]")
    prev, offset = "v0", 0.0
    for i in range(1, n):
        offset += durations[i - 1]
        parts.append(f"[{prev}][v{i}]xfade=transition=fade:duration={FADE}:offset={offset:.2f}[x{i}]")
        prev = f"x{i}"

    out_path = out_dir / "reel.mp4"
    cmd += [
        "-filter_complex", ";".join(parts),
        "-map", f"[{prev}]", "-map", f"{2 * n}:a",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "27", "-maxrate", "3M", "-bufsize", "6M",
        "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", str(FPS), "-g", str(FPS * 2),
        "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
        "-t", f"{total:.2f}", "-movflags", "+faststart", str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"    footage reel failed: {result.stderr.strip()[:300]}")
        return None
    (out_dir / "reel_version.txt").write_text(VERSION, encoding="utf-8")
    return out_path
