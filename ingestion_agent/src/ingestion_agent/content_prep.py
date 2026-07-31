"""Lightweight content preparation artifacts for downstream agents."""

from __future__ import annotations

import json
import logging
import math
from pathlib import Path
from typing import Any, Optional

from ingestion_agent.config import Config
from ingestion_agent.ffprobe import (
    detect_scene_changes,
    detect_silences,
    extract_thumbnail,
    measure_loudness,
)
from ingestion_agent.models import ContentPlaceholders, RecordingMetadata

logger = logging.getLogger("ingestion_agent.content_prep")


class ContentPreparer:
    """Generate placeholders and lightweight indexes for a recording.

    Heavy AI analysis (viral moments, clips, full transcripts) is intentionally
    left as placeholders for downstream agents.
    """

    def __init__(self, config: Config) -> None:
        """Create a preparer bound to configuration.

        Args:
            config: Loaded agent configuration.
        """
        self.config = config
        self.settings = config.content_prep()

    async def prepare(
        self,
        source: Path,
        output_dir: Path,
        metadata: RecordingMetadata,
    ) -> ContentPlaceholders:
        """Build content-prep artifacts beside the stored recording.

        Args:
            source: Path to the stored video file (or original during prep).
            output_dir: Destination directory for generated artifacts.
            metadata: Extracted recording metadata.

        Returns:
            A :class:`ContentPlaceholders` instance.
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        placeholders = ContentPlaceholders()
        duration = metadata.duration_seconds or 0.0

        # Always emit AI placeholders requested by the pipeline contract.
        for name in self.settings.get("placeholders") or []:
            if name == "transcript":
                placeholders.transcript = {
                    "status": "pending",
                    "segments": [],
                    "note": "Reserved for transcription agent",
                }
            elif name == "motion_analysis":
                placeholders.motion_analysis = {"status": "pending"}
            elif name == "face_detection":
                placeholders.face_detection = {"status": "pending"}
            elif name == "ocr":
                placeholders.ocr = {"status": "pending"}
            elif name == "chat_overlay_detection":
                placeholders.chat_overlay_detection = {"status": "pending"}

        filenames = self.config.storage_filenames()

        if self.settings.get("generate_thumbnail", True):
            preview_path = output_dir / filenames["preview"]
            at = min(5.0, max(0.0, duration * 0.1 if duration else 0.0))
            try:
                await extract_thumbnail(source, preview_path, at_seconds=at)
                placeholders.thumbnail = str(preview_path)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Thumbnail generation failed: %s",
                    exc,
                    extra={"path": str(source), "event": "thumbnail_failed"},
                )
                placeholders.thumbnail = None

        if self.settings.get("generate_timestamp_index", True):
            interval = float(self.settings.get("timestamp_interval_seconds", 30))
            placeholders.timestamp_index = build_timestamp_index(duration, interval)

        if self.settings.get("generate_waveform", True):
            samples = int(self.settings.get("waveform_samples", 200))
            placeholders.audio_waveform = synthesize_waveform_placeholder(duration, samples)

        if self.settings.get("generate_silence_map", True):
            try:
                placeholders.silence_map = await detect_silences(
                    source,
                    threshold_db=float(self.settings.get("silence_threshold_db", -50)),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Silence map failed: %s", exc)
                placeholders.silence_map = []

        if self.settings.get("generate_loudness", True):
            try:
                placeholders.loudness_graph = await measure_loudness(source)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Loudness measurement failed: %s", exc)
                placeholders.loudness_graph = []

        if self.settings.get("generate_scene_index", True):
            try:
                placeholders.scene_change_index = await detect_scene_changes(
                    source,
                    threshold=float(self.settings.get("scene_threshold", 0.4)),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Scene index failed: %s", exc)
                placeholders.scene_change_index = []

        if self.settings.get("generate_chapter_suggestions", True):
            placeholders.chapter_suggestions = suggest_chapters(
                duration=duration,
                scene_changes=placeholders.scene_change_index,
                timeline_markers=[m.__dict__ for m in metadata.timeline_markers],
                min_gap=float(self.settings.get("chapter_min_gap_seconds", 120)),
                game=metadata.game_title,
            )

        # Persist content prep bundle for downstream agents.
        prep_path = output_dir / "content_prep.json"
        with prep_path.open("w", encoding="utf-8") as fh:
            json.dump(placeholders.to_dict(), fh, indent=2)

        return placeholders


def build_timestamp_index(duration: float, interval: float) -> list[dict[str, Any]]:
    """Build a regular timestamp index across the recording.

    Args:
        duration: Total duration in seconds.
        interval: Spacing between timestamps.

    Returns:
        List of ``{\"index\", \"timestamp\"}`` entries.
    """
    if duration <= 0 or interval <= 0:
        return [{"index": 0, "timestamp": 0.0}]
    points: list[dict[str, Any]] = []
    t = 0.0
    idx = 0
    while t <= duration + 1e-6:
        points.append({"index": idx, "timestamp": round(min(t, duration), 3)})
        idx += 1
        t += interval
    if points[-1]["timestamp"] < duration:
        points.append({"index": idx, "timestamp": round(duration, 3)})
    return points


def synthesize_waveform_placeholder(duration: float, samples: int) -> list[float]:
    """Create a deterministic pseudo-waveform for pipeline scaffolding.

    A real amplitude envelope can replace this later; ingestion only needs a
    stable artifact that downstream UIs can render.

    Args:
        duration: Recording duration (used to seed shape).
        samples: Number of waveform samples.

    Returns:
        List of floats in ``[0, 1]``.
    """
    if samples <= 0:
        return []
    wave: list[float] = []
    length_factor = max(duration, 1.0)
    for i in range(samples):
        x = i / max(samples - 1, 1)
        # Smooth envelope with mild variation — not derived from real audio.
        value = 0.35 + 0.35 * abs(math.sin(x * math.pi * 4 + length_factor)) * (0.5 + 0.5 * math.sin(x * 12))
        wave.append(round(min(1.0, max(0.0, value)), 4))
    return wave


def suggest_chapters(
    duration: float,
    scene_changes: list[dict[str, Any]],
    timeline_markers: list[dict[str, Any]],
    min_gap: float = 120.0,
    game: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Suggest chapter boundaries from markers and scene changes.

    Args:
        duration: Total duration in seconds.
        scene_changes: Scene change index entries.
        timeline_markers: Game/application timeline markers.
        min_gap: Minimum seconds between chapters.
        game: Optional default chapter title.

    Returns:
        Ordered chapter suggestion dictionaries.
    """
    candidates: list[tuple[float, str]] = [(0.0, game or "Start")]

    for marker in timeline_markers:
        start = float(marker.get("start_seconds") or 0.0)
        label = str(marker.get("label") or "Segment")
        if start > 0:
            candidates.append((start, label))

    for scene in scene_changes:
        ts = float(scene.get("timestamp") or 0.0)
        if ts > 0:
            candidates.append((ts, f"Scene @ {int(ts // 60):02d}:{int(ts % 60):02d}"))

    candidates.sort(key=lambda item: item[0])
    chapters: list[dict[str, Any]] = []
    last_t = -min_gap
    for ts, title in candidates:
        if ts - last_t < min_gap and chapters:
            continue
        chapters.append(
            {
                "start": round(ts, 3),
                "title": title,
                "end": None,
            }
        )
        last_t = ts

    for i, chapter in enumerate(chapters):
        if i + 1 < len(chapters):
            chapter["end"] = chapters[i + 1]["start"]
        else:
            chapter["end"] = round(duration, 3) if duration else None
    return chapters
