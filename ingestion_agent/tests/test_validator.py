"""Tests for recording validation logic."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ingestion_agent.config import Config
from ingestion_agent.validator import RecordingValidator, aspect_ratio, parse_frame_rate, wait_until_stable
from tests.helpers import make_test_video


def test_parse_frame_rate() -> None:
    """Fractional and integer frame rates parse correctly."""
    assert parse_frame_rate("30") == 30.0
    assert abs((parse_frame_rate("30000/1001") or 0) - 29.97) < 0.01
    assert parse_frame_rate("0/0") is None


def test_aspect_ratio() -> None:
    """Aspect ratio simplifies correctly."""
    assert aspect_ratio(1920, 1080) == "16:9"
    assert aspect_ratio(None, 1080) is None


@pytest.mark.asyncio
async def test_wait_until_stable(tmp_path: Path) -> None:
    """Stability helper returns True when size stops changing."""
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"12345")
    ok = await wait_until_stable(path, stability_seconds=0.15, check_interval=0.05, timeout=2)
    assert ok is True


@pytest.mark.asyncio
async def test_validate_real_video(test_config: Config, tmp_path: Path) -> None:
    """A short generated video passes validation with test thresholds."""
    video = make_test_video(tmp_path / "ok.mp4", duration=2.5)
    validator = RecordingValidator(test_config)
    result = await validator.validate(video, skip_stability=True)
    assert result.ok is True
    assert result.has_video is True
    assert result.has_audio is True
    assert result.duration_seconds is not None
    assert result.duration_seconds > 1
    assert result.resolution == "640x360"


@pytest.mark.asyncio
async def test_reject_too_short(test_config: Config, tmp_path: Path) -> None:
    """Videos under the minimum duration are rejected."""
    video = make_test_video(tmp_path / "short.mp4", duration=0.5)
    # Raise min duration above the clip length.
    test_config.raw["validation"]["min_duration_seconds"] = 10
    validator = RecordingValidator(test_config)
    result = await validator.validate(video, skip_stability=True)
    assert result.ok is False
    assert any("Duration" in r for r in result.reasons)


@pytest.mark.asyncio
async def test_reject_corrupt(test_config: Config, tmp_path: Path) -> None:
    """Corrupt bytes that ffprobe cannot open are rejected."""
    path = tmp_path / "bad.mp4"
    path.write_bytes(b"this is not a video")
    validator = RecordingValidator(test_config)
    result = await validator.validate(path, skip_stability=True)
    assert result.ok is False
    assert any("opened" in r.lower() or "ffprobe" in r.lower() for r in result.reasons)
