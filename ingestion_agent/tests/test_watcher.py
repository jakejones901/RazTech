"""Tests for watch-directory scanning and ignore rules."""

from __future__ import annotations

from pathlib import Path

import pytest

from ingestion_agent.config import Config
from ingestion_agent.watcher import RecordingWatcher, should_ignore


def test_should_ignore_temp_and_hidden() -> None:
    """Temp, partial, and hidden names are ignored."""
    patterns = [".*", "*.tmp", "*.part"]
    assert should_ignore(Path(".hidden.mp4"), patterns)
    assert should_ignore(Path("clip.tmp"), patterns)
    assert should_ignore(Path("clip.mp4.part"), patterns)
    assert not should_ignore(Path("final.mp4"), patterns)


@pytest.mark.asyncio
async def test_scan_once_finds_new_files(test_config: Config, tmp_roots: dict[str, Path]) -> None:
    """Watcher discovers supported video files once."""
    video = tmp_roots["recordings"] / "stream.mkv"
    video.write_bytes(b"not-a-real-video")
    ignored = tmp_roots["recordings"] / "stream.mp4.part"
    ignored.write_bytes(b"partial")

    seen: list[Path] = []

    async def cb(path: Path) -> None:
        seen.append(path)

    watcher = RecordingWatcher(test_config, on_detected=cb)
    found = watcher.scan_once()
    assert len(found) == 1
    assert found[0].path.name == "stream.mkv"

    # Second scan should not re-report known paths after marking.
    watcher.known_paths.add(str(found[0].path.resolve()))
    assert watcher.scan_once() == []
