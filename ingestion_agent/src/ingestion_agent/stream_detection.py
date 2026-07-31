"""Heuristics for detecting game, application, streaming software, and OS."""

from __future__ import annotations

import json
import platform
import re
from pathlib import Path
from typing import Any, Optional

from ingestion_agent.models import TimelineMarker


class StreamDetector:
    """Infer stream context from filenames, sidecars, and path structure."""

    def __init__(
        self,
        known_games: Optional[list[str]] = None,
        streaming_software: Optional[list[str]] = None,
        platforms: Optional[list[str]] = None,
    ) -> None:
        """Create a detector with configured vocabularies.

        Args:
            known_games: Game titles to match in names/paths.
            streaming_software: Streaming software names to detect.
            platforms: Streaming platforms to detect.
        """
        self.known_games = known_games or []
        self.streaming_software = streaming_software or ["OBS", "OBS Studio", "Streamlabs"]
        self.platforms = platforms or ["Twitch", "YouTube", "Kick"]

    def detect(self, path: Path, probe_tags: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Detect stream context for a recording.

        Args:
            path: Path to the recording.
            probe_tags: Optional format tags from ffprobe.

        Returns:
            Dictionary with game_title, application, streaming_software,
            operating_system, platform, and timeline_markers.
        """
        probe_tags = probe_tags or {}
        text_blob = " ".join(
            [
                path.name,
                str(path.parent),
                str(probe_tags.get("title", "")),
                str(probe_tags.get("comment", "")),
                str(probe_tags.get("description", "")),
            ]
        )

        sidecar = self._load_sidecar(path)
        games_found = self._find_all(text_blob, self.known_games)
        if sidecar.get("game"):
            games_found.insert(0, str(sidecar["game"]))
        if sidecar.get("games") and isinstance(sidecar["games"], list):
            for g in sidecar["games"]:
                if g and str(g) not in games_found:
                    games_found.append(str(g))

        # Deduplicate preserving order
        seen: set[str] = set()
        unique_games: list[str] = []
        for g in games_found:
            key = g.lower()
            if key not in seen:
                seen.add(key)
                unique_games.append(g)

        software = self._find_first(text_blob, self.streaming_software)
        if not software:
            # Path heuristics
            lowered = str(path).lower()
            if "/obs/" in lowered or "\\obs\\" in lowered or "obs" in path.parts:
                software = "OBS Studio"
            elif "streamlabs" in lowered:
                software = "Streamlabs"

        platform_name = self._find_first(text_blob, self.platforms) or sidecar.get("platform")
        application = sidecar.get("application")
        if not application and unique_games:
            application = unique_games[0]

        duration = None
        try:
            if probe_tags.get("_duration"):
                duration = float(probe_tags["_duration"])
        except (TypeError, ValueError):
            duration = None

        timeline = self._build_timeline(unique_games, sidecar, duration)

        return {
            "game_title": unique_games[0] if unique_games else sidecar.get("game"),
            "games": unique_games,
            "application": application,
            "streaming_software": software or sidecar.get("streaming_software"),
            "operating_system": sidecar.get("operating_system") or platform.system(),
            "platform": platform_name,
            "timeline_markers": timeline,
        }

    def _load_sidecar(self, path: Path) -> dict[str, Any]:
        """Load sidecar JSON if present."""
        for candidate in (
            path.with_suffix(".json"),
            path.parent / "metadata.json",
            path.parent / "stream.json",
        ):
            if candidate.is_file():
                try:
                    with candidate.open("r", encoding="utf-8") as fh:
                        data = json.load(fh)
                    if isinstance(data, dict):
                        return data
                except (OSError, json.JSONDecodeError):
                    continue
        return {}

    def _find_all(self, text: str, vocabulary: list[str]) -> list[str]:
        """Return all vocabulary terms found in *text* (case-insensitive)."""
        lower = text.lower()
        found: list[str] = []
        # Prefer longer names first to avoid partial overlaps
        for term in sorted(vocabulary, key=len, reverse=True):
            if term.lower() in lower:
                found.append(term)
        return found

    def _find_first(self, text: str, vocabulary: list[str]) -> Optional[str]:
        """Return the first vocabulary match in *text*."""
        matches = self._find_all(text, vocabulary)
        return matches[0] if matches else None

    def _build_timeline(
        self,
        games: list[str],
        sidecar: dict[str, Any],
        duration: Optional[float],
    ) -> list[TimelineMarker]:
        """Build timeline markers for one or more games.

        If the sidecar provides explicit segments, those are preferred.
        Otherwise a single marker covering the whole recording is created
        per detected game (equal splits when multiple games are present).
        """
        markers: list[TimelineMarker] = []

        segments = sidecar.get("segments") or sidecar.get("timeline") or []
        if isinstance(segments, list) and segments:
            for seg in segments:
                if not isinstance(seg, dict):
                    continue
                try:
                    markers.append(
                        TimelineMarker(
                            start_seconds=float(seg.get("start", 0)),
                            end_seconds=float(seg["end"]) if seg.get("end") is not None else None,
                            label=str(seg.get("label") or seg.get("game") or "segment"),
                            kind=str(seg.get("kind") or "game"),
                            confidence=float(seg.get("confidence", 0.8)),
                        )
                    )
                except (TypeError, ValueError):
                    continue
            return markers

        if not games:
            return markers

        if len(games) == 1:
            markers.append(
                TimelineMarker(
                    start_seconds=0.0,
                    end_seconds=duration,
                    label=games[0],
                    kind="game",
                    confidence=0.6,
                )
            )
            return markers

        # Multiple games without explicit segments → equal time splits as placeholders.
        if duration and duration > 0:
            slice_len = duration / len(games)
            for idx, game in enumerate(games):
                start = idx * slice_len
                end = duration if idx == len(games) - 1 else (idx + 1) * slice_len
                markers.append(
                    TimelineMarker(
                        start_seconds=start,
                        end_seconds=end,
                        label=game,
                        kind="game",
                        confidence=0.4,
                    )
                )
        else:
            for game in games:
                markers.append(
                    TimelineMarker(
                        start_seconds=0.0,
                        end_seconds=None,
                        label=game,
                        kind="game",
                        confidence=0.3,
                    )
                )
        return markers


def parse_game_from_obs_filename(filename: str) -> Optional[str]:
    """Extract a plausible game/scene name from a typical OBS filename.

    Args:
        filename: Recording file name.

    Returns:
        Detected name or ``None``.
    """
    stem = Path(filename).stem
    match = re.match(r"^(?P<name>.+?)[\s_\-]+\d{4}[-_]\d{2}[-_]\d{2}", stem)
    if match:
        return match.group("name").strip(" _-") or None
    return None
