"""Tests for configuration loading and path helpers."""

from __future__ import annotations

from pathlib import Path

import yaml

from ingestion_agent.config import load_config, normalize_path


def test_load_default_config() -> None:
    """Default YAML loads with expected watch extensions."""
    cfg = load_config()
    assert ".mp4" in cfg.extensions
    assert cfg.next_agent == "Clip Detection Agent"
    assert cfg.id_prefix == "RAZ"


def test_env_overrides(tmp_path: Path, monkeypatch) -> None:
    """Environment variables override storage roots."""
    content = tmp_path / "c"
    failed = tmp_path / "f"
    monkeypatch.setenv("INGESTION_CONTENT_ROOT", str(content))
    monkeypatch.setenv("INGESTION_FAILED_ROOT", str(failed))
    monkeypatch.setenv("INGESTION_STABILITY_SECONDS", "12")
    cfg = load_config()
    assert cfg.content_root == normalize_path(str(content))
    assert cfg.failed_root == normalize_path(str(failed))
    assert cfg.stability_seconds == 12.0


def test_local_override_merge(tmp_path: Path) -> None:
    """Explicit override file merges into defaults."""
    override = {"pipeline": {"creator": "TestCreator"}, "validation": {"min_duration_seconds": 5}}
    path = tmp_path / "local.yaml"
    path.write_text(yaml.safe_dump(override), encoding="utf-8")
    cfg = load_config(path)
    assert cfg.creator == "TestCreator"
    assert cfg.min_duration_seconds == 5
    assert cfg.next_agent == "Clip Detection Agent"


def test_normalize_relative_path(tmp_path: Path, monkeypatch) -> None:
    """Relative paths resolve against the working directory."""
    monkeypatch.chdir(tmp_path)
    resolved = normalize_path("relative/dir")
    assert resolved == tmp_path / "relative" / "dir" or str(resolved).endswith(
        str(Path("relative") / "dir")
    )
