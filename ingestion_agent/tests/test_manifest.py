"""Tests for manifest construction."""

from __future__ import annotations

import json
from pathlib import Path

from ingestion_agent.config import Config
from ingestion_agent.manifest import ManifestBuilder
from ingestion_agent.models import RecordingMetadata


def test_manifest_fields(test_config: Config, tmp_path: Path) -> None:
    """Manifest includes required handoff fields."""
    meta = RecordingMetadata(
        filename="original.mp4",
        file_path="/imports/original.mp4",
        recording_date="2026-07-31",
        duration_seconds=321.5,
        game_title="Minecraft",
        tags=["recording", "minecraft"],
    )
    builder = ManifestBuilder(test_config)
    out = tmp_path / "out"
    out.mkdir()
    manifest = builder.build(
        video_id="RAZ-20260731-001",
        metadata=meta,
        checksum="abc123",
        output_directory=out,
    )
    path = builder.write(manifest, out / "manifest.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["unique_id"] == "RAZ-20260731-001"
    assert data["next_agent"] == "Clip Detection Agent"
    assert data["checksum"] == "sha256:abc123"
    assert data["game"] == "Minecraft"
    assert data["status"] == "ready"
    assert data["creator"] == "RazTech"
