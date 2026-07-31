"""Tests for game / platform / timeline detection heuristics."""

from __future__ import annotations

from pathlib import Path

from ingestion_agent.stream_detection import StreamDetector, parse_game_from_obs_filename


def test_detect_game_and_obs_from_path(tmp_path: Path) -> None:
    """Filename and path reveal game and streaming software."""
    path = tmp_path / "obs" / "output" / "Valorant 2026-07-31 12-00-00.mp4"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x")
    detector = StreamDetector(
        known_games=["Valorant", "Minecraft"],
        streaming_software=["OBS Studio", "Streamlabs"],
        platforms=["Twitch", "YouTube"],
    )
    result = detector.detect(path)
    assert result["game_title"] == "Valorant"
    assert result["streaming_software"] == "OBS Studio"
    assert len(result["timeline_markers"]) >= 1


def test_multiple_games_create_timeline_markers(tmp_path: Path) -> None:
    """Multiple games yield separate timeline markers."""
    path = tmp_path / "imports" / "Valorant_and_Minecraft_twitch.mp4"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"x")
    detector = StreamDetector(known_games=["Valorant", "Minecraft"], platforms=["Twitch"])
    result = detector.detect(path, probe_tags={"_duration": 600})
    assert set(result["games"]) >= {"Valorant", "Minecraft"}
    assert len(result["timeline_markers"]) == 2
    assert result["platform"] == "Twitch"


def test_parse_game_from_obs_filename() -> None:
    """OBS-style filenames yield a scene/game prefix."""
    assert parse_game_from_obs_filename("Gameplay_2026-07-31_01-02-03.mkv") == "Gameplay"
