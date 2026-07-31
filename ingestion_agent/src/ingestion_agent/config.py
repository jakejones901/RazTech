"""Configuration loading and path normalization for the Ingestion Agent."""

from __future__ import annotations

import os
import platform
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

import yaml

DEFAULT_CONFIG_NAME = "default.yaml"
ENV_CONFIG_PATH = "INGESTION_CONFIG"
ENV_PREFIX = "INGESTION_"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into *base* and return a new dict."""
    result = deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def normalize_path(path_str: str) -> Path:
    """Normalize a configured path for the current operating system.

    Absolute POSIX-style paths like ``/content`` are kept as-is on Linux and
    mapped under the current drive root on Windows (e.g. ``C:\\content``).
    Relative paths resolve against the process working directory. Environment
    variables and ``~`` are expanded.
    """
    expanded = os.path.expandvars(os.path.expanduser(path_str))
    path = Path(expanded)

    if platform.system() == "Windows":
        # Treat leading-/ POSIX roots as drive-relative absolute paths.
        text = str(path)
        if text.startswith("/") and not path.drive:
            drive = Path.cwd().drive or "C:"
            path = Path(f"{drive}/{text.lstrip('/')}")
        return path.resolve() if path.exists() or path.is_absolute() else Path(path)

    return path if path.is_absolute() else (Path.cwd() / path)


class Config:
    """Typed accessor around the ingestion agent YAML configuration."""

    def __init__(self, data: dict[str, Any], source_path: Optional[Path] = None) -> None:
        """Initialize with a loaded configuration dictionary.

        Args:
            data: Fully merged configuration mapping.
            source_path: Optional path the config was loaded from.
        """
        self._data = data
        self.source_path = source_path

    @property
    def raw(self) -> dict[str, Any]:
        """Return the underlying configuration dictionary."""
        return self._data

    def get(self, *keys: str, default: Any = None) -> Any:
        """Fetch a nested value by key path.

        Args:
            *keys: Nested key sequence (e.g. ``\"watch\", \"poll_interval_seconds\"``).
            default: Value returned when the key path is missing.

        Returns:
            The configured value or *default*.
        """
        node: Any = self._data
        for key in keys:
            if not isinstance(node, dict) or key not in node:
                return default
            node = node[key]
        return node

    @property
    def pipeline_version(self) -> str:
        """Pipeline version string stamped into manifests."""
        return str(self.get("pipeline", "version", default="1.0.0"))

    @property
    def creator(self) -> str:
        """Content creator / brand name."""
        return str(self.get("pipeline", "creator", default="RazTech"))

    @property
    def project(self) -> str:
        """Project name for manifests."""
        return str(self.get("pipeline", "project", default="AI Content Pipeline"))

    @property
    def next_agent(self) -> str:
        """Name of the downstream agent to notify."""
        return str(self.get("pipeline", "next_agent", default="Clip Detection Agent"))

    @property
    def priority(self) -> str:
        """Default processing priority."""
        return str(self.get("pipeline", "priority", default="normal"))

    @property
    def id_prefix(self) -> str:
        """Prefix used when generating video IDs."""
        return str(self.get("pipeline", "id_prefix", default="RAZ"))

    @property
    def watch_directories(self) -> list[Path]:
        """Directories monitored for new recordings."""
        dirs = self.get("watch", "directories", default=[]) or []
        return [normalize_path(str(d)) for d in dirs]

    @property
    def extensions(self) -> set[str]:
        """Accepted video file extensions (lowercase, with dot)."""
        exts = self.get("watch", "extensions", default=[".mp4", ".mkv", ".mov", ".avi"]) or []
        return {e.lower() if e.startswith(".") else f".{e.lower()}" for e in exts}

    @property
    def ignore_patterns(self) -> list[str]:
        """Glob-style patterns for files that must be ignored."""
        return list(self.get("watch", "ignore_patterns", default=[]) or [])

    @property
    def poll_interval_seconds(self) -> float:
        """Watcher poll interval in seconds."""
        return float(self.get("watch", "poll_interval_seconds", default=5))

    @property
    def recursive_watch(self) -> bool:
        """Whether watch directories are scanned recursively."""
        return bool(self.get("watch", "recursive", default=True))

    @property
    def stability_seconds(self) -> float:
        """Seconds a file size must remain unchanged before processing."""
        return float(self.get("validation", "stability_seconds", default=60))

    @property
    def stability_check_interval_seconds(self) -> float:
        """Interval between size-stability checks."""
        return float(self.get("validation", "stability_check_interval_seconds", default=5))

    @property
    def min_duration_seconds(self) -> float:
        """Minimum accepted recording duration in seconds."""
        return float(self.get("validation", "min_duration_seconds", default=120))

    @property
    def require_video_stream(self) -> bool:
        """Whether a video stream is mandatory."""
        return bool(self.get("validation", "require_video_stream", default=True))

    @property
    def require_audio_stream(self) -> bool:
        """Whether an audio stream is mandatory."""
        return bool(self.get("validation", "require_audio_stream", default=True))

    @property
    def ffprobe_timeout_seconds(self) -> float:
        """Timeout for ffprobe invocations."""
        return float(self.get("validation", "ffprobe_timeout_seconds", default=60))

    @property
    def content_root(self) -> Path:
        """Root directory for successfully ingested content."""
        return normalize_path(str(self.get("storage", "content_root", default="/content")))

    @property
    def failed_root(self) -> Path:
        """Root directory for failed ingestions."""
        return normalize_path(str(self.get("storage", "failed_root", default="/failed")))

    @property
    def max_concurrent(self) -> int:
        """Maximum number of recordings processed in parallel."""
        return int(self.get("processing", "max_concurrent", default=2))

    def content_prep(self) -> dict[str, Any]:
        """Return the content preparation subsection."""
        return dict(self.get("content_prep", default={}) or {})

    def stream_detection(self) -> dict[str, Any]:
        """Return the stream detection subsection."""
        return dict(self.get("stream_detection", default={}) or {})

    def storage_filenames(self) -> dict[str, str]:
        """Return configured output filenames."""
        storage = self.get("storage", default={}) or {}
        return {
            "video": storage.get("video_filename", "video.mp4"),
            "manifest": storage.get("manifest_filename", "manifest.json"),
            "metadata": storage.get("metadata_filename", "metadata.json"),
            "log": storage.get("log_filename", "processing.log"),
            "hash": storage.get("hash_filename", "hash.txt"),
            "preview": storage.get("preview_filename", "preview.jpg"),
            "failure_report": storage.get("failure_report_filename", "failure_report.json"),
        }


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """Apply selected environment variable overrides.

    Supported variables:
        INGESTION_CONTENT_ROOT, INGESTION_FAILED_ROOT,
        INGESTION_WATCH_DIRS (os.pathsep-separated),
        INGESTION_LOG_LEVEL, INGESTION_STABILITY_SECONDS,
        INGESTION_MIN_DURATION_SECONDS, INGESTION_MAX_CONCURRENT
    """
    result = deepcopy(data)
    result.setdefault("storage", {})
    result.setdefault("watch", {})
    result.setdefault("validation", {})
    result.setdefault("logging", {})
    result.setdefault("processing", {})

    if value := os.environ.get("INGESTION_CONTENT_ROOT"):
        result["storage"]["content_root"] = value
    if value := os.environ.get("INGESTION_FAILED_ROOT"):
        result["storage"]["failed_root"] = value
    if value := os.environ.get("INGESTION_WATCH_DIRS"):
        result["watch"]["directories"] = [p for p in value.split(os.pathsep) if p]
    if value := os.environ.get("INGESTION_LOG_LEVEL"):
        result["logging"]["level"] = value
    if value := os.environ.get("INGESTION_STABILITY_SECONDS"):
        result["validation"]["stability_seconds"] = float(value)
    if value := os.environ.get("INGESTION_MIN_DURATION_SECONDS"):
        result["validation"]["min_duration_seconds"] = float(value)
    if value := os.environ.get("INGESTION_MAX_CONCURRENT"):
        result["processing"]["max_concurrent"] = int(value)
    return result


def default_config_path() -> Path:
    """Return the packaged default configuration path."""
    # ingestion_agent/config/default.yaml relative to this package's parents
    package_root = Path(__file__).resolve().parents[2]
    candidate = package_root / "config" / DEFAULT_CONFIG_NAME
    if candidate.exists():
        return candidate
    # Installed / alternate layout
    alt = Path(__file__).resolve().parents[1] / "config" / DEFAULT_CONFIG_NAME
    return alt


def load_config(path: Optional[str | Path] = None) -> Config:
    """Load configuration from YAML, merging defaults, local overrides, and env.

    Resolution order:
        1. Packaged ``default.yaml``
        2. Explicit *path*, or ``INGESTION_CONFIG``, or ``config/local.yaml`` beside defaults
        3. Environment variable overrides

    Args:
        path: Optional path to a user/local YAML config file.

    Returns:
        A ready-to-use :class:`Config` instance.

    Raises:
        FileNotFoundError: If the default config cannot be found.
        yaml.YAMLError: If a config file is invalid YAML.
    """
    default_path = default_config_path()
    if not default_path.exists():
        raise FileNotFoundError(f"Default config not found: {default_path}")

    with default_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    override_path: Optional[Path] = None
    if path is not None:
        override_path = Path(path)
    elif os.environ.get(ENV_CONFIG_PATH):
        override_path = Path(os.environ[ENV_CONFIG_PATH])
    else:
        local = default_path.parent / "local.yaml"
        if local.exists():
            override_path = local

    source = default_path
    if override_path and override_path.exists():
        with override_path.open("r", encoding="utf-8") as fh:
            override = yaml.safe_load(fh) or {}
        data = _deep_merge(data, override)
        source = override_path

    data = _apply_env_overrides(data)
    return Config(data, source_path=source)
