"""Test helpers shared across modules."""

from __future__ import annotations

import subprocess
from pathlib import Path


def make_test_video(path: Path, duration: float = 3.0, with_audio: bool = True) -> Path:
    """Generate a synthetic test video using ffmpeg.

    Args:
        path: Destination path (suffix selects container).
        duration: Length in seconds.
        with_audio: Whether to include an audio track.

    Returns:
        The created path.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    args = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=blue:s=640x360:d={duration}",
    ]
    if with_audio:
        args += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}"]
    args += ["-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-t", str(duration)]
    if with_audio:
        args += ["-c:a", "aac"]
    args.append(str(path))
    proc = subprocess.run(args, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not path.exists():
        raise RuntimeError(f"ffmpeg failed: {proc.stderr}")
    return path
