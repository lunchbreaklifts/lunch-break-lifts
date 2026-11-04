"""
Background music for the YouTube and Facebook copies of each Reel.

Instagram adds a trending song from its own library at publish time, but that song doesn't
travel with the video, so the copies elsewhere would be silent. For those, a royalty-free
song from music/ (Pixabay Content License, checked to have no Content ID registration when
added; see music/tracks.json) is mixed in. Instagram itself is unchanged.
"""

import random
import shutil
import subprocess
import tempfile
from pathlib import Path

from common import ROOT

MUSIC_DIR = ROOT / "music"


def tracks():
    return sorted(p for p in MUSIC_DIR.glob("*.mp3") if p.stat().st_size > 50_000)


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def with_music(video, post_id):
    """Return (path to a copy of `video` with a song mixed in, song file name), or (None, "")
    if there are no songs or ffmpeg isn't available. The same post always gets the same song."""
    songs = tracks()
    if not songs or not shutil.which("ffmpeg"):
        return None, ""
    song = random.Random(post_id).choice(songs)
    length = duration(video) or 30.0
    fade_at = max(0.0, length - 1.2)
    out = Path(tempfile.mkdtemp()) / "reel_music.mp4"
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(video), "-stream_loop", "-1", "-i", str(song),
           "-filter_complex", f"[1:a]volume=0.85,afade=t=in:d=0.3,afade=t=out:st={fade_at:.2f}:d=1.2[a]",
           "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "48000",
           "-t", f"{length:.2f}", "-movflags", "+faststart", str(out)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not out.exists():
        print(f"    couldn't add music for the other sites ({result.stderr.strip()[:200]})")
        return None, ""
    return out, song.stem
