"""Metadata extraction from recordings and sidecar clues."""

from __future__ import annotations

import json
import platform
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ingestion_agent.models import (
    AudioStreamInfo,
    RecordingMetadata,
    TimelineMarker,
    ValidationResult,
    VideoStreamInfo,
    to_iso,
)
from ingestion_agent.validator import aspect_ratio, parse_frame_rate


def _file_times(path: Path) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Return (recording_date, creation_time, last_modified_time) as ISO strings."""
    try:
        stat = path.stat()
    except OSError:
        return None, None, None

    mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    # st_ctime is creation on Windows; metadata-change time on Linux.
    ctime = datetime.fromtimestamp(stat.st_ctime, tz=timezone.utc)
    birth: Optional[datetime] = None
    if hasattr(stat, "st_birthtime"):
        try:
            birth = datetime.fromtimestamp(stat.st_birthtime, tz=timezone.utc)  # type: ignore[attr-defined]
        except (AttributeError, OSError, OverflowError):
            birth = None

    creation = birth or ctime
    recording_date = creation.date().isoformat()
    return recording_date, to_iso(creation), to_iso(mtime)


def _guess_language(audio_streams: list[dict[str, Any]], tags: dict[str, Any]) -> Optional[str]:
    """Estimate language from stream or format tags."""
    for stream in audio_streams:
        lang = (stream.get("tags") or {}).get("language")
        if lang and lang.lower() not in {"und", "unknown"}:
            return lang
    for key in ("language", "LANGUAGE"):
        if tags.get(key):
            return str(tags[key])
    return None


def _read_obs_sidecar(path: Path) -> dict[str, Any]:
    """Read optional OBS / recorder sidecar JSON next to the recording.

    Looks for ``<stem>.json``, ``<name>.json``, or ``metadata.json`` in the same folder.
    """
    candidates = [
        path.with_suffix(".json"),
        path.parent / f"{path.name}.json",
        path.parent / "metadata.json",
        path.parent / "obs.json",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            try:
                with candidate.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    return data
            except (OSError, json.JSONDecodeError):
                continue
    return {}


def _from_filename_hints(filename: str, known_games: list[str]) -> dict[str, Optional[str]]:
    """Infer game / platform / OBS scene hints from the filename."""
    result: dict[str, Optional[str]] = {
        "game_title": None,
        "platform": None,
        "obs_scene_name": None,
        "window_title": None,
    }
    lower = filename.lower()
    for game in known_games:
        if game.lower() in lower:
            result["game_title"] = game
            break

    for platform_name in ("twitch", "youtube", "kick", "trovo"):
        if platform_name in lower:
            result["platform"] = platform_name.title() if platform_name != "youtube" else "YouTube"
            break

    # Common OBS pattern: SceneName YYYY-MM-DD HH-MM-SS.mp4
    stem = Path(filename).stem
    scene_match = re.match(
        r"^(?P<scene>.+?)[\s_\-]+\d{4}[-_]\d{2}[-_]\d{2}",
        stem,
    )
    if scene_match and not result["game_title"]:
        scene = scene_match.group("scene").strip(" _-")
        if scene and len(scene) < 80:
            result["obs_scene_name"] = scene
            result["window_title"] = scene

    # Bracketed titles: [Game Name] ...
    bracket = re.search(r"\[([^\]]+)\]", filename)
    if bracket and not result["game_title"]:
        result["game_title"] = bracket.group(1).strip()
        result["window_title"] = result["window_title"] or result["game_title"]

    return result


class MetadataExtractor:
    """Build rich :class:`RecordingMetadata` from probe data and filesystem clues."""

    def __init__(self, known_games: Optional[list[str]] = None) -> None:
        """Initialize the extractor.

        Args:
            known_games: Optional list of game titles used for filename matching.
        """
        self.known_games = known_games or []

    def extract(
        self,
        path: Path,
        validation: ValidationResult,
        stream_info: Optional[dict[str, Any]] = None,
    ) -> RecordingMetadata:
        """Extract metadata for a validated recording.

        Args:
            path: Path to the recording file.
            validation: Prior validation result (includes probe data).
            stream_info: Optional stream-detection results to merge in.

        Returns:
            Populated :class:`RecordingMetadata`.
        """
        probe_data = validation.probe_data or {}
        streams = probe_data.get("streams") or []
        fmt = probe_data.get("format") or {}
        tags = fmt.get("tags") or {}

        video_raw = [s for s in streams if s.get("codec_type") == "video"]
        audio_raw = [s for s in streams if s.get("codec_type") == "audio"]

        video_streams: list[VideoStreamInfo] = []
        for vs in video_raw:
            w, h = vs.get("width"), vs.get("height")
            video_streams.append(
                VideoStreamInfo(
                    codec=vs.get("codec_name"),
                    width=w,
                    height=h,
                    frame_rate=parse_frame_rate(vs.get("r_frame_rate")),
                    bitrate=int(vs["bit_rate"]) if vs.get("bit_rate") else None,
                    aspect_ratio=aspect_ratio(w, h),
                    pix_fmt=vs.get("pix_fmt"),
                )
            )

        audio_streams: list[AudioStreamInfo] = []
        for aus in audio_raw:
            audio_streams.append(
                AudioStreamInfo(
                    codec=aus.get("codec_name"),
                    sample_rate=int(aus["sample_rate"]) if aus.get("sample_rate") else None,
                    channels=aus.get("channels"),
                    bitrate=int(aus["bit_rate"]) if aus.get("bit_rate") else None,
                    language=(aus.get("tags") or {}).get("language"),
                )
            )

        recording_date, creation_time, last_modified = _file_times(path)
        # Prefer format tags for creation if present (OBS often writes them).
        for key in ("creation_time", "DATE", "date"):
            if tags.get(key):
                creation_time = str(tags[key])
                try:
                    recording_date = datetime.fromisoformat(
                        creation_time.replace("Z", "+00:00")
                    ).date().isoformat()
                except ValueError:
                    pass
                break

        hints = _from_filename_hints(path.name, self.known_games)
        sidecar = _read_obs_sidecar(path)

        game_title = (
            (stream_info or {}).get("game_title")
            or sidecar.get("game")
            or sidecar.get("game_title")
            or hints["game_title"]
            or tags.get("game")
            or tags.get("title")
        )
        obs_scene = (
            sidecar.get("scene")
            or sidecar.get("obs_scene_name")
            or hints["obs_scene_name"]
        )
        window_title = (
            sidecar.get("window_title")
            or hints["window_title"]
            or tags.get("title")
        )
        platform_name = (
            (stream_info or {}).get("platform")
            or sidecar.get("platform")
            or hints["platform"]
        )

        bitrate = None
        if fmt.get("bit_rate"):
            try:
                bitrate = int(fmt["bit_rate"])
            except (TypeError, ValueError):
                bitrate = None

        container = (fmt.get("format_name") or path.suffix.lstrip(".") or None)
        if isinstance(container, str) and "," in container:
            # ffprobe may return "mov,mp4,m4a,..." — prefer the file suffix.
            container = path.suffix.lstrip(".").lower() or container.split(",")[0]

        primary_video = video_streams[0] if video_streams else None
        primary_audio = audio_streams[0] if audio_streams else None

        timeline_markers: list[TimelineMarker] = []
        if stream_info and stream_info.get("timeline_markers"):
            for marker in stream_info["timeline_markers"]:
                if isinstance(marker, TimelineMarker):
                    timeline_markers.append(marker)
                elif isinstance(marker, dict):
                    timeline_markers.append(TimelineMarker(**marker))

        meta = RecordingMetadata(
            filename=path.name,
            file_path=str(path.resolve()),
            recording_date=recording_date,
            creation_time=creation_time,
            last_modified_time=last_modified,
            duration_seconds=validation.duration_seconds,
            file_size_bytes=path.stat().st_size if path.exists() else None,
            video_codec=validation.video_codec or (primary_video.codec if primary_video else None),
            audio_codec=validation.audio_codec or (primary_audio.codec if primary_audio else None),
            bitrate=bitrate,
            resolution=validation.resolution
            or (
                f"{primary_video.width}x{primary_video.height}"
                if primary_video and primary_video.width and primary_video.height
                else None
            ),
            frame_rate=validation.frame_rate
            or (primary_video.frame_rate if primary_video else None),
            aspect_ratio=primary_video.aspect_ratio if primary_video else None,
            container_type=container,
            audio_track_count=len(audio_streams),
            audio_sample_rate=primary_audio.sample_rate if primary_audio else None,
            obs_scene_name=obs_scene,
            game_title=str(game_title) if game_title else None,
            window_title=str(window_title) if window_title else None,
            platform=str(platform_name) if platform_name else None,
            estimated_language=_guess_language(audio_raw, tags),
            application=(stream_info or {}).get("application"),
            streaming_software=(stream_info or {}).get("streaming_software"),
            operating_system=(stream_info or {}).get("operating_system") or platform.system(),
            video_streams=video_streams,
            audio_streams=audio_streams,
            timeline_markers=timeline_markers,
            tags=_build_tags(game_title, platform_name, obs_scene),
            extra={"format_tags": tags, "sidecar": sidecar},
        )
        return meta


def _build_tags(
    game: Optional[str],
    platform_name: Optional[str],
    scene: Optional[str],
) -> list[str]:
    """Build a short tag list from high-signal fields."""
    tags: list[str] = ["recording", "ingestion"]
    if game:
        tags.append(str(game).lower().replace(" ", "-"))
    if platform_name:
        tags.append(str(platform_name).lower().replace(" ", "-"))
    if scene:
        tags.append(f"scene:{scene}")
    return tags
