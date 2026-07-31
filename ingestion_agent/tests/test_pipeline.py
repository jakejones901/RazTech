"""End-to-end ingestion pipeline tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ingestion_agent.config import Config
from ingestion_agent.pipeline import IngestionPipeline, recommended_fix_for
from tests.helpers import make_test_video


def test_recommended_fix_for_duration() -> None:
    """Duration failures map to a clear remediation."""
    fix = recommended_fix_for("Duration 10.00s is not greater than 120s")
    assert "longer" in fix.lower()


@pytest.mark.asyncio
async def test_pipeline_success(
    test_config: Config,
    sample_video: Path,
    tmp_roots: dict[str, Path],
) -> None:
    """A valid recording produces SUCCESS artifacts and notifies next agent."""
    pipeline = IngestionPipeline(test_config)
    result = await pipeline.process_file(
        sample_video,
        skip_stability=True,
        copy=False,
        move_on_failure=True,
    )
    assert result.success is True
    assert result.video_id is not None
    assert result.video_id.startswith("RAZ-")
    assert result.next_agent == "Clip Detection Agent"
    assert result.game == "Valorant"
    assert result.output_directory is not None
    out = Path(result.output_directory)
    assert (out / "video.mp4").exists()
    assert (out / "manifest.json").exists()
    assert (out / "metadata.json").exists()
    assert (out / "processing.log").exists()
    assert (out / "hash.txt").exists()
    assert (out / "content_prep.json").exists()
    assert (out / "preview.jpg").exists()
    notice = out / ".pipeline" / f"{result.video_id}.notify.json"
    assert notice.exists()

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["unique_id"] == result.video_id
    assert manifest["next_agent"] == "Clip Detection Agent"

    text = result.format_output()
    assert text.startswith("SUCCESS")
    assert "Clip Detection Agent" in text


@pytest.mark.asyncio
async def test_pipeline_failure_corrupt(
    test_config: Config,
    tmp_roots: dict[str, Path],
) -> None:
    """Corrupt input yields FAILED output and a failure report."""
    bad = tmp_roots["imports"] / "corrupt.mp4"
    bad.write_bytes(b"not a video file at all")
    pipeline = IngestionPipeline(test_config)
    result = await pipeline.process_file(
        bad,
        skip_stability=True,
        move_on_failure=True,
    )
    assert result.success is False
    assert result.reason
    assert result.recommended_fix
    assert result.log_location
    failed_root = tmp_roots["failed"]
    reports = list(failed_root.rglob("failure_report.json"))
    assert reports, "expected failure_report.json under /failed"
    text = result.format_output()
    assert text.startswith("FAILED")


@pytest.mark.asyncio
async def test_ids_do_not_collide(
    test_config: Config,
    tmp_roots: dict[str, Path],
) -> None:
    """Sequential ingestions allocate distinct IDs."""
    pipeline = IngestionPipeline(test_config)
    ids: list[str] = []
    for idx in range(2):
        video = make_test_video(
            tmp_roots["imports"] / f"Minecraft_run_{idx}.mp4",
            duration=2.0,
        )
        result = await pipeline.process_file(video, skip_stability=True)
        assert result.success
        assert result.video_id
        ids.append(result.video_id)
    assert ids[0] != ids[1]
