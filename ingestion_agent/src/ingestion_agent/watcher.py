"""Directory watcher that detects newly completed recordings."""

from __future__ import annotations

import asyncio
import fnmatch
import logging
from pathlib import Path
from typing import Awaitable, Callable, Optional

from ingestion_agent.config import Config
from ingestion_agent.models import DetectedFile, utc_now

logger = logging.getLogger("ingestion_agent.watcher")

ProcessCallback = Callable[[Path], Awaitable[None]]


def should_ignore(path: Path, ignore_patterns: list[str]) -> bool:
    """Return True if *path* matches an ignore pattern or is hidden.

    Args:
        path: Candidate file path.
        ignore_patterns: Glob-style patterns from configuration.

    Returns:
        Whether the file should be ignored.
    """
    name = path.name
    if name.startswith("."):
        return True
    for pattern in ignore_patterns:
        if fnmatch.fnmatch(name, pattern) or fnmatch.fnmatch(str(path), pattern):
            return True
    # Common partial / temp suffixes
    lower = name.lower()
    for suffix in (".tmp", ".temp", ".part", ".partial", ".crdownload", ".download"):
        if lower.endswith(suffix):
            return True
    return False


class RecordingWatcher:
    """Poll watch directories for new video files and enqueue them for processing.

    A polling strategy is used for reliable cross-platform behavior (Windows and
    Linux) and to pair cleanly with size-stability checks in the validator.
    """

    def __init__(
        self,
        config: Config,
        on_detected: ProcessCallback,
        known_paths: Optional[set[str]] = None,
    ) -> None:
        """Create a watcher.

        Args:
            config: Loaded agent configuration.
            on_detected: Async callback invoked with each new stable candidate
                path. The callback should perform (or schedule) ingestion.
            known_paths: Optional set of already-seen absolute path strings.
        """
        self.config = config
        self.on_detected = on_detected
        self.known_paths: set[str] = known_paths or set()
        self._running = False
        self._in_flight: set[str] = set()

    def scan_once(self) -> list[DetectedFile]:
        """Scan watch directories once and return newly seen candidates.

        Returns:
            List of :class:`DetectedFile` instances not previously known.
        """
        found: list[DetectedFile] = []
        for directory in self.config.watch_directories:
            if not directory.exists():
                logger.debug(
                    "Watch directory missing: %s",
                    directory,
                    extra={"path": str(directory), "event": "watch_missing"},
                )
                continue
            iterator = directory.rglob("*") if self.config.recursive_watch else directory.iterdir()
            for path in iterator:
                if not path.is_file():
                    continue
                if path.suffix.lower() not in self.config.extensions:
                    continue
                if should_ignore(path, self.config.ignore_patterns):
                    continue
                key = str(path.resolve())
                if key in self.known_paths or key in self._in_flight:
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                detected = DetectedFile(path=path.resolve(), detected_at=utc_now(), size_bytes=size)
                found.append(detected)
                logger.info(
                    "Detected candidate recording",
                    extra={"path": key, "event": "detected"},
                )
        return found

    async def run(self, stop_event: Optional[asyncio.Event] = None) -> None:
        """Continuously poll watch directories until stopped.

        Args:
            stop_event: Optional event that terminates the loop when set.
        """
        self._running = True
        stop_event = stop_event or asyncio.Event()
        logger.info(
            "Watcher started",
            extra={
                "event": "watcher_start",
                "path": ",".join(str(d) for d in self.config.watch_directories),
            },
        )
        try:
            while self._running and not stop_event.is_set():
                candidates = self.scan_once()
                for item in candidates:
                    key = str(item.path)
                    self._in_flight.add(key)
                    try:
                        await self.on_detected(item.path)
                    finally:
                        self.known_paths.add(key)
                        self._in_flight.discard(key)
                try:
                    await asyncio.wait_for(
                        stop_event.wait(),
                        timeout=self.config.poll_interval_seconds,
                    )
                except asyncio.TimeoutError:
                    continue
        finally:
            self._running = False
            logger.info("Watcher stopped", extra={"event": "watcher_stop"})

    def stop(self) -> None:
        """Request that the watcher loop terminate."""
        self._running = False
