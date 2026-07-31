"""Async wrappers around ffprobe / ffmpeg for media inspection."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any, Optional


class MediaToolError(RuntimeError):
    """Raised when ffprobe or ffmpeg fails or is unavailable."""


def which_ffprobe() -> Optional[str]:
    """Locate the ``ffprobe`` executable on PATH.

    Returns:
        Absolute path string, or ``None`` if not found.
    """
    return shutil.which("ffprobe")


def which_ffmpeg() -> Optional[str]:
    """Locate the ``ffmpeg`` executable on PATH.

    Returns:
        Absolute path string, or ``None`` if not found.
    """
    return shutil.which("ffmpeg")


async def run_command(
    args: list[str],
    timeout: float = 60.0,
) -> tuple[int, str, str]:
    """Run a subprocess asynchronously and capture output.

    Args:
        args: Command and arguments.
        timeout: Maximum seconds to wait.

    Returns:
        Tuple of ``(returncode, stdout, stderr)``.

    Raises:
        MediaToolError: On timeout or OS-level launch failure.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise MediaToolError(f"Executable not found: {args[0]}") from exc

    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        proc.kill()
        await proc.communicate()
        raise MediaToolError(f"Command timed out after {timeout}s: {' '.join(args)}") from exc

    return proc.returncode or 0, stdout_b.decode("utf-8", errors="replace"), stderr_b.decode(
        "utf-8", errors="replace"
    )


async def probe(path: Path, timeout: float = 60.0) -> dict[str, Any]:
    """Probe a media file with ffprobe and return parsed JSON.

    Args:
        path: Path to the media file.
        timeout: Subprocess timeout in seconds.

    Returns:
        Parsed ffprobe JSON dictionary.

    Raises:
        MediaToolError: If ffprobe is missing, fails, or returns invalid JSON.
    """
    ffprobe = which_ffprobe()
    if not ffprobe:
        raise MediaToolError("ffprobe is not installed or not on PATH")

    args = [
        ffprobe,
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        "-show_chapters",
        str(path),
    ]
    code, stdout, stderr = await run_command(args, timeout=timeout)
    if code != 0:
        raise MediaToolError(f"ffprobe failed ({code}): {stderr.strip() or 'unknown error'}")
    try:
        return json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise MediaToolError(f"ffprobe returned invalid JSON: {exc}") from exc


async def extract_thumbnail(
    source: Path,
    destination: Path,
    at_seconds: float = 5.0,
    timeout: float = 60.0,
) -> Path:
    """Extract a single JPEG preview frame with ffmpeg.

    Args:
        source: Source video path.
        destination: Output JPEG path.
        at_seconds: Timestamp to sample.
        timeout: Subprocess timeout.

    Returns:
        The destination path.

    Raises:
        MediaToolError: If ffmpeg fails.
    """
    ffmpeg = which_ffmpeg()
    if not ffmpeg:
        raise MediaToolError("ffmpeg is not installed or not on PATH")

    destination.parent.mkdir(parents=True, exist_ok=True)
    args = [
        ffmpeg,
        "-y",
        "-ss",
        str(max(0.0, at_seconds)),
        "-i",
        str(source),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(destination),
    ]
    code, _stdout, stderr = await run_command(args, timeout=timeout)
    if code != 0 or not destination.exists():
        raise MediaToolError(f"thumbnail extraction failed: {stderr.strip()}")
    return destination


async def detect_silences(
    source: Path,
    threshold_db: float = -50.0,
    min_silence: float = 0.5,
    timeout: float = 300.0,
) -> list[dict[str, float]]:
    """Detect silent regions using ffmpeg's silencedetect filter.

    Args:
        source: Source video/audio path.
        threshold_db: Silence noise tolerance in dB.
        min_silence: Minimum silence duration in seconds.
        timeout: Subprocess timeout.

    Returns:
        List of ``{\"start\", \"end\", \"duration\"}`` dictionaries.
    """
    ffmpeg = which_ffmpeg()
    if not ffmpeg:
        return []

    args = [
        ffmpeg,
        "-i",
        str(source),
        "-af",
        f"silencedetect=noise={threshold_db}dB:d={min_silence}",
        "-f",
        "null",
        "-",
    ]
    _code, _stdout, stderr = await run_command(args, timeout=timeout)

    silences: list[dict[str, float]] = []
    current_start: Optional[float] = None
    for line in stderr.splitlines():
        if "silence_start:" in line:
            try:
                current_start = float(line.split("silence_start:")[1].strip().split()[0])
            except (IndexError, ValueError):
                current_start = None
        elif "silence_end:" in line and current_start is not None:
            try:
                parts = line.split("silence_end:")[1].strip().split("|")
                end = float(parts[0].strip().split()[0])
                duration = end - current_start
                if "silence_duration:" in line:
                    duration = float(line.split("silence_duration:")[1].strip().split()[0])
                silences.append({"start": current_start, "end": end, "duration": duration})
            except (IndexError, ValueError):
                pass
            current_start = None
    return silences


async def detect_scene_changes(
    source: Path,
    threshold: float = 0.4,
    timeout: float = 300.0,
) -> list[dict[str, float]]:
    """Detect scene-change timestamps using ffmpeg's select+showinfo filters.

    Args:
        source: Source video path.
        threshold: Scene change sensitivity (0–1).
        timeout: Subprocess timeout.

    Returns:
        List of ``{\"timestamp\", \"score\"}`` dictionaries.
    """
    ffmpeg = which_ffmpeg()
    if not ffmpeg:
        return []

    args = [
        ffmpeg,
        "-i",
        str(source),
        "-filter:v",
        f"select='gt(scene,{threshold})',showinfo",
        "-f",
        "null",
        "-",
    ]
    _code, _stdout, stderr = await run_command(args, timeout=timeout)

    scenes: list[dict[str, float]] = []
    for line in stderr.splitlines():
        if "pts_time:" not in line:
            continue
        try:
            pts = float(line.split("pts_time:")[1].split()[0])
            score = threshold
            if "scene_score" in line:
                # showinfo may include lavfi.scene_score=...
                for token in line.replace(":", " ").split():
                    if token.startswith("lavfi.scene_score"):
                        # format varies; ignore if unparsable
                        pass
            scenes.append({"timestamp": pts, "score": score})
        except (IndexError, ValueError):
            continue
    return scenes


async def measure_loudness(
    source: Path,
    timeout: float = 300.0,
) -> list[dict[str, Any]]:
    """Measure integrated loudness via ffmpeg ebur128.

    Args:
        source: Source media path.
        timeout: Subprocess timeout.

    Returns:
        A short loudness summary list suitable for graphing placeholders.
    """
    ffmpeg = which_ffmpeg()
    if not ffmpeg:
        return []

    args = [
        ffmpeg,
        "-i",
        str(source),
        "-filter_complex",
        "ebur128=peak=true",
        "-f",
        "null",
        "-",
    ]
    _code, _stdout, stderr = await run_command(args, timeout=timeout)

    points: list[dict[str, Any]] = []
    for line in stderr.splitlines():
        if "I:" in line and "LUFS" in line and "Summary" not in line:
            # Momentary / short-term lines are noisy; capture summary at end.
            continue
        if "Integrated loudness:" in line or (line.strip().startswith("I:") and "LUFS" in line):
            try:
                # Summary block: "I:         -23.0 LUFS"
                value = float(line.split("I:")[1].split("LUFS")[0].strip())
                points.append({"metric": "integrated_lufs", "value": value})
            except (IndexError, ValueError):
                continue
        if "Loudness range:" in line or (line.strip().startswith("LRA:") and "LU" in line):
            try:
                value = float(line.split("LRA:")[1].split("LU")[0].strip())
                points.append({"metric": "lra", "value": value})
            except (IndexError, ValueError):
                continue
    return points
