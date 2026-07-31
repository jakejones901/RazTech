"""Recording file validation (stability, openability, stream requirements)."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

from ingestion_agent.config import Config
from ingestion_agent.ffprobe import MediaToolError, probe
from ingestion_agent.models import ValidationResult

logger = logging.getLogger("ingestion_agent.validator")


def parse_frame_rate(rate: Optional[str]) -> Optional[float]:
    """Parse an ffprobe frame-rate string such as ``30000/1001`` or ``30``.

    Args:
        rate: Raw frame-rate string from ffprobe.

    Returns:
        Frames per second as float, or ``None`` if unparsable.
    """
    if not rate or rate in {"0/0", "N/A"}:
        return None
    try:
        if "/" in rate:
            num, den = rate.split("/", 1)
            den_f = float(den)
            if den_f == 0:
                return None
            return float(num) / den_f
        return float(rate)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def aspect_ratio(width: Optional[int], height: Optional[int]) -> Optional[str]:
    """Compute a simplified width:height aspect ratio string.

    Args:
        width: Frame width in pixels.
        height: Frame height in pixels.

    Returns:
        Ratio string such as ``16:9``, or ``None``.
    """
    if not width or not height:
        return None

    def gcd(a: int, b: int) -> int:
        while b:
            a, b = b, a % b
        return a

    g = gcd(width, height)
    return f"{width // g}:{height // g}"


async def wait_until_stable(
    path: Path,
    stability_seconds: float = 60.0,
    check_interval: float = 5.0,
    timeout: Optional[float] = None,
) -> bool:
    """Wait until the file size has not changed for *stability_seconds*.

    Args:
        path: File to monitor.
        stability_seconds: Required unchanged duration.
        check_interval: Sleep between size checks.
        timeout: Optional overall timeout. Defaults to ``stability_seconds * 10``.

    Returns:
        ``True`` if the file stabilized; ``False`` on timeout or disappearance.
    """
    if not path.exists():
        return False

    deadline = time.monotonic() + (timeout if timeout is not None else stability_seconds * 10)
    last_size = -1
    stable_since: Optional[float] = None

    while time.monotonic() < deadline:
        try:
            size = path.stat().st_size
        except OSError:
            return False

        now = time.monotonic()
        if size == last_size and size > 0:
            if stable_since is None:
                stable_since = now
            elif now - stable_since >= stability_seconds:
                logger.info(
                    "File size stable",
                    extra={"path": str(path), "event": "stability_ok"},
                )
                return True
        else:
            last_size = size
            stable_since = now if size > 0 else None

        await asyncio.sleep(check_interval)

    logger.warning(
        "File did not stabilize in time",
        extra={"path": str(path), "event": "stability_timeout"},
    )
    return False


class RecordingValidator:
    """Validate that a recording is finished, openable, and meets quality gates."""

    def __init__(self, config: Config) -> None:
        """Create a validator bound to configuration.

        Args:
            config: Loaded agent configuration.
        """
        self.config = config

    async def validate(self, path: Path, *, skip_stability: bool = False) -> ValidationResult:
        """Run full validation on a recording.

        Args:
            path: Absolute path to the candidate recording.
            skip_stability: When True, skip the size-stability wait (useful in tests).

        Returns:
            A :class:`ValidationResult` describing success or rejection reasons.
        """
        reasons: list[str] = []
        warnings: list[str] = []

        if not path.exists():
            return ValidationResult(ok=False, reasons=["File does not exist"])

        if path.name.startswith("."):
            return ValidationResult(ok=False, reasons=["Hidden files are ignored"])

        if path.suffix.lower() not in self.config.extensions:
            return ValidationResult(
                ok=False,
                reasons=[f"Unsupported extension: {path.suffix}"],
            )

        try:
            size = path.stat().st_size
        except OSError as exc:
            return ValidationResult(ok=False, reasons=[f"Cannot stat file: {exc}"])

        if size <= 0:
            return ValidationResult(ok=False, reasons=["File is empty"])

        if not skip_stability:
            stable = await wait_until_stable(
                path,
                stability_seconds=self.config.stability_seconds,
                check_interval=self.config.stability_check_interval_seconds,
            )
            if not stable:
                return ValidationResult(
                    ok=False,
                    reasons=[
                        f"File size did not remain unchanged for "
                        f"{self.config.stability_seconds} seconds "
                        "(still being written or inaccessible)"
                    ],
                )

        try:
            data = await probe(path, timeout=self.config.ffprobe_timeout_seconds)
        except MediaToolError as exc:
            logger.error(
                "ffprobe validation failure",
                extra={"path": str(path), "event": "probe_failed", "reason": str(exc)},
            )
            return ValidationResult(
                ok=False,
                reasons=[f"Video could not be opened: {exc}"],
            )

        streams = data.get("streams") or []
        fmt = data.get("format") or {}
        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

        has_video = len(video_streams) > 0
        has_audio = len(audio_streams) > 0

        duration: Optional[float] = None
        try:
            if fmt.get("duration") is not None:
                duration = float(fmt["duration"])
            elif video_streams and video_streams[0].get("duration") is not None:
                duration = float(video_streams[0]["duration"])
        except (TypeError, ValueError):
            duration = None

        video_codec = video_streams[0].get("codec_name") if video_streams else None
        audio_codec = audio_streams[0].get("codec_name") if audio_streams else None

        width = video_streams[0].get("width") if video_streams else None
        height = video_streams[0].get("height") if video_streams else None
        resolution = f"{width}x{height}" if width and height else None
        frame_rate = parse_frame_rate(video_streams[0].get("r_frame_rate") if video_streams else None)

        if self.config.require_video_stream and not has_video:
            reasons.append("No video stream found")
        if self.config.require_audio_stream and not has_audio:
            reasons.append("No audio stream found")
        if duration is None:
            reasons.append("Duration could not be determined")
        elif duration <= self.config.min_duration_seconds:
            reasons.append(
                f"Duration {duration:.2f}s is not greater than "
                f"{self.config.min_duration_seconds}s"
            )
        if has_video and not video_codec:
            reasons.append("Video codec missing")
        if has_video and not resolution:
            reasons.append("Resolution could not be determined")
        if has_video and frame_rate is None:
            warnings.append("Frame rate could not be determined")

        ok = len(reasons) == 0
        result = ValidationResult(
            ok=ok,
            reasons=reasons,
            warnings=warnings,
            duration_seconds=duration,
            has_video=has_video,
            has_audio=has_audio,
            video_codec=video_codec,
            audio_codec=audio_codec,
            resolution=resolution,
            frame_rate=frame_rate,
            probe_data=data,
        )
        logger.info(
            "Validation %s" % ("passed" if ok else "failed"),
            extra={
                "path": str(path),
                "event": "validation_result",
                "reason": "; ".join(reasons) if reasons else "ok",
            },
        )
        return result
