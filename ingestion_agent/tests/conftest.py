"""Shared pytest fixtures for the Ingestion Agent test suite."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ingestion_agent.config import Config, load_config
from tests.helpers import make_test_video


@pytest.fixture
def tmp_roots(tmp_path: Path) -> dict[str, Path]:
    """Create temporary watch / content / failed directories."""
    roots = {
        "recordings": tmp_path / "streams" / "recordings",
        "obs": tmp_path / "obs" / "output",
        "imports": tmp_path / "imports",
        "content": tmp_path / "content",
        "failed": tmp_path / "failed",
    }
    for path in roots.values():
        path.mkdir(parents=True, exist_ok=True)
    return roots


@pytest.fixture
def test_config(tmp_path: Path, tmp_roots: dict[str, Path]) -> Config:
    """Load default config overridden for fast, isolated tests."""
    override = {
        "watch": {
            "directories": [
                str(tmp_roots["recordings"]),
                str(tmp_roots["obs"]),
                str(tmp_roots["imports"]),
            ],
            "poll_interval_seconds": 0.1,
        },
        "validation": {
            "stability_seconds": 0.2,
            "stability_check_interval_seconds": 0.05,
            "min_duration_seconds": 1,
            "ffprobe_timeout_seconds": 30,
        },
        "storage": {
            "content_root": str(tmp_roots["content"]),
            "failed_root": str(tmp_roots["failed"]),
        },
        "content_prep": {
            "generate_waveform": True,
            "generate_silence_map": False,
            "generate_loudness": False,
            "generate_scene_index": False,
            "generate_chapter_suggestions": True,
            "generate_thumbnail": True,
        },
        "logging": {"level": "WARNING", "format": "text", "console": False},
        "processing": {"max_concurrent": 1, "notify_on_complete": True},
    }
    cfg_path = tmp_path / "test_config.yaml"
    with cfg_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(override, fh)
    return load_config(cfg_path)


@pytest.fixture
def sample_video(tmp_roots: dict[str, Path]) -> Path:
    """Create a short valid mp4 in the imports watch directory."""
    dest = tmp_roots["imports"] / "Valorant_2026-07-31_12-00-00.mp4"
    return make_test_video(dest, duration=3.0, with_audio=True)
