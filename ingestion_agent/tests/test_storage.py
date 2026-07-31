"""Tests for content store layout and failure handling."""

from __future__ import annotations

import json
from pathlib import Path

from ingestion_agent.config import Config
from ingestion_agent.models import RecordingMetadata
from ingestion_agent.storage import StorageManager, compute_sha256, date_parts
from tests.helpers import make_test_video


def test_date_parts_from_iso() -> None:
    """ISO and compact dates resolve to YYYY/MM/DD."""
    assert date_parts("2026-07-31") == ("2026", "07", "31")
    assert date_parts("20260731") == ("2026", "07", "31")


def test_store_recording_layout(test_config: Config, tmp_path: Path) -> None:
    """Stored recordings land under dated ID directories with required artifacts."""
    source = make_test_video(tmp_path / "src.mp4", duration=2.0)
    meta = RecordingMetadata(
        filename=source.name,
        file_path=str(source),
        recording_date="2026-07-31",
        duration_seconds=2.0,
        game_title="Valorant",
    )
    storage = StorageManager(test_config)
    result = storage.store_recording(source, "RAZ-20260731-001", meta, copy=True)
    assert result.directory.name == "RAZ-20260731-001"
    assert result.video.name == "video.mp4"
    assert result.video.exists()
    assert result.hash_file.exists()
    assert result.metadata.exists()
    assert result.checksum == compute_sha256(result.video)
    payload = json.loads(result.metadata.read_text(encoding="utf-8"))
    assert payload["game_title"] == "Valorant"


def test_fail_recording_writes_report(test_config: Config, tmp_path: Path) -> None:
    """Failed ingestions produce failure_report.json under /failed."""
    source = tmp_path / "broken.mp4"
    source.write_bytes(b"nope")
    storage = StorageManager(test_config)
    failed_dir, report = storage.fail_recording(
        source,
        reason="corrupt",
        recommended_fix="re-export",
        move=True,
    )
    assert failed_dir.exists()
    report_path = failed_dir / test_config.storage_filenames()["failure_report"]
    assert report_path.exists()
    data = json.loads(report_path.read_text(encoding="utf-8"))
    assert data["reason"] == "corrupt"
    assert report.recommended_fix == "re-export"
