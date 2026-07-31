"""Tests for content preparation helpers."""

from __future__ import annotations

from ingestion_agent.content_prep import (
    build_timestamp_index,
    suggest_chapters,
    synthesize_waveform_placeholder,
)


def test_timestamp_index_covers_duration() -> None:
    """Timestamp index includes start and end."""
    index = build_timestamp_index(90, 30)
    stamps = [i["timestamp"] for i in index]
    assert stamps[0] == 0.0
    assert stamps[-1] == 90


def test_waveform_length() -> None:
    """Waveform placeholder has the requested sample count."""
    wave = synthesize_waveform_placeholder(120, 50)
    assert len(wave) == 50
    assert all(0.0 <= v <= 1.0 for v in wave)


def test_chapter_suggestions_respect_min_gap() -> None:
    """Chapters are spaced by the configured minimum gap."""
    scenes = [{"timestamp": t} for t in (10, 20, 200, 210)]
    chapters = suggest_chapters(
        duration=400,
        scene_changes=scenes,
        timeline_markers=[{"start_seconds": 0, "label": "Intro"}],
        min_gap=100,
        game="Valorant",
    )
    assert chapters[0]["start"] == 0.0
    starts = [c["start"] for c in chapters]
    for a, b in zip(starts, starts[1:]):
        assert b - a >= 100
