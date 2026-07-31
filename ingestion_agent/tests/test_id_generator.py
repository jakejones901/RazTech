"""Tests for unique video ID generation."""

from __future__ import annotations

from pathlib import Path

from ingestion_agent.id_generator import IdGenerator


def test_generate_format_and_sequence(tmp_path: Path) -> None:
    """IDs follow RAZ-YYYYMMDD-NNN and increment without collisions."""
    gen = IdGenerator(tmp_path / "content", prefix="RAZ")
    first = gen.generate(date_str="20260731")
    second = gen.generate(date_str="20260731")
    assert first == "RAZ-20260731-001"
    assert second == "RAZ-20260731-002"
    assert first != second


def test_never_overwrite_existing_on_disk(tmp_path: Path) -> None:
    """Existing on-disk IDs are skipped."""
    content = tmp_path / "content" / "2026" / "07" / "31"
    content.mkdir(parents=True)
    (content / "RAZ-20260731-001").mkdir()
    (content / "RAZ-20260731-002").mkdir()
    gen = IdGenerator(tmp_path / "content", prefix="RAZ")
    nxt = gen.generate(date_str="20260731")
    assert nxt == "RAZ-20260731-003"


def test_release_allows_reuse_of_reservation(tmp_path: Path) -> None:
    """Released reservations can be reused when not on disk."""
    gen = IdGenerator(tmp_path / "content", prefix="RAZ")
    vid = gen.generate(date_str="20260731")
    gen.release(vid)
    again = gen.generate(date_str="20260731")
    assert again == "RAZ-20260731-001"
