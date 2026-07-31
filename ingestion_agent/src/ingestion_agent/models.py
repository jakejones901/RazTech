"""Data models for the Ingestion Agent."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional


def utc_now() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(timezone.utc)


def to_iso(dt: Optional[datetime]) -> Optional[str]:
    """Serialize a datetime to ISO-8601, or None."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


class ProcessingStatus(str, Enum):
    """Lifecycle status for an ingested recording."""

    DETECTED = "detected"
    VALIDATING = "validating"
    EXTRACTING = "extracting"
    PREPARING = "preparing"
    STORING = "storing"
    READY = "ready"
    FAILED = "failed"


@dataclass
class VideoStreamInfo:
    """Technical details for a single video stream."""

    codec: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    frame_rate: Optional[float] = None
    bitrate: Optional[int] = None
    aspect_ratio: Optional[str] = None
    pix_fmt: Optional[str] = None


@dataclass
class AudioStreamInfo:
    """Technical details for a single audio stream."""

    codec: Optional[str] = None
    sample_rate: Optional[int] = None
    channels: Optional[int] = None
    bitrate: Optional[int] = None
    language: Optional[str] = None


@dataclass
class TimelineMarker:
    """Marker indicating a game or application segment within a recording."""

    start_seconds: float
    end_seconds: Optional[float]
    label: str
    kind: str = "game"  # game | application | scene
    confidence: float = 0.5


@dataclass
class RecordingMetadata:
    """Full metadata extracted from a recording file."""

    filename: str
    file_path: str
    recording_date: Optional[str] = None
    creation_time: Optional[str] = None
    last_modified_time: Optional[str] = None
    duration_seconds: Optional[float] = None
    file_size_bytes: Optional[int] = None
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    bitrate: Optional[int] = None
    resolution: Optional[str] = None
    frame_rate: Optional[float] = None
    aspect_ratio: Optional[str] = None
    container_type: Optional[str] = None
    audio_track_count: int = 0
    audio_sample_rate: Optional[int] = None
    obs_scene_name: Optional[str] = None
    game_title: Optional[str] = None
    window_title: Optional[str] = None
    platform: Optional[str] = None
    estimated_language: Optional[str] = None
    application: Optional[str] = None
    streaming_software: Optional[str] = None
    operating_system: Optional[str] = None
    video_streams: list[VideoStreamInfo] = field(default_factory=list)
    audio_streams: list[AudioStreamInfo] = field(default_factory=list)
    timeline_markers: list[TimelineMarker] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""
        return asdict(self)


@dataclass
class ContentPlaceholders:
    """Placeholders and lightweight indexes prepared for downstream agents."""

    transcript: dict[str, Any] = field(default_factory=lambda: {"status": "pending", "segments": []})
    thumbnail: Optional[str] = None
    audio_waveform: list[float] = field(default_factory=list)
    scene_change_index: list[dict[str, Any]] = field(default_factory=list)
    timestamp_index: list[dict[str, Any]] = field(default_factory=list)
    silence_map: list[dict[str, Any]] = field(default_factory=list)
    loudness_graph: list[dict[str, Any]] = field(default_factory=list)
    chapter_suggestions: list[dict[str, Any]] = field(default_factory=list)
    motion_analysis: dict[str, Any] = field(default_factory=lambda: {"status": "pending"})
    face_detection: dict[str, Any] = field(default_factory=lambda: {"status": "pending"})
    ocr: dict[str, Any] = field(default_factory=lambda: {"status": "pending"})
    chat_overlay_detection: dict[str, Any] = field(default_factory=lambda: {"status": "pending"})

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""
        return asdict(self)


@dataclass
class Manifest:
    """Machine-readable handoff document for the next pipeline agent."""

    unique_id: str
    video_filename: str
    original_location: str
    duration: float
    game: Optional[str]
    recording_date: Optional[str]
    creator: str
    project: str
    status: str
    pipeline_version: str
    checksum: str
    next_agent: str
    priority: str
    tags: list[str] = field(default_factory=list)
    output_directory: Optional[str] = None
    metadata_path: Optional[str] = None
    content_prep_path: Optional[str] = None
    created_at: str = field(default_factory=lambda: to_iso(utc_now()) or "")

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""
        return asdict(self)


@dataclass
class ValidationResult:
    """Outcome of recording validation."""

    ok: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duration_seconds: Optional[float] = None
    has_video: bool = False
    has_audio: bool = False
    video_codec: Optional[str] = None
    audio_codec: Optional[str] = None
    resolution: Optional[str] = None
    frame_rate: Optional[float] = None
    probe_data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""
        return asdict(self)


@dataclass
class FailureReport:
    """Structured report written when validation or processing fails."""

    source_path: str
    failed_at: str
    reason: str
    recommended_fix: str
    details: dict[str, Any] = field(default_factory=dict)
    log_location: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary."""
        return asdict(self)


@dataclass
class IngestionResult:
    """Final result returned by the ingestion pipeline for one recording."""

    success: bool
    video_id: Optional[str] = None
    duration: Optional[float] = None
    game: Optional[str] = None
    output_directory: Optional[str] = None
    manifest_location: Optional[str] = None
    next_agent: Optional[str] = None
    reason: Optional[str] = None
    recommended_fix: Optional[str] = None
    log_location: Optional[str] = None

    def format_output(self) -> str:
        """Format the human/machine-readable terminal output specified by the pipeline contract."""
        if self.success:
            return (
                "SUCCESS\n"
                f"Video ID: {self.video_id}\n"
                f"Duration: {self.duration}\n"
                f"Game: {self.game}\n"
                f"Output directory: {self.output_directory}\n"
                f"Manifest location: {self.manifest_location}\n"
                f"Next Agent:\n{self.next_agent}"
            )
        return (
            "FAILED\n"
            f"Reason: {self.reason}\n"
            f"Recommended Fix: {self.recommended_fix}\n"
            f"Log Location: {self.log_location}"
        )


@dataclass
class DetectedFile:
    """A candidate recording discovered by the watcher."""

    path: Path
    detected_at: datetime = field(default_factory=utc_now)
    size_bytes: int = 0
