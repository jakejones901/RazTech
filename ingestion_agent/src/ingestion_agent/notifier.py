"""Notify the next pipeline agent after successful ingestion."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from ingestion_agent.models import Manifest

logger = logging.getLogger("ingestion_agent.notifier")


class NextAgentNotifier:
    """Write a handoff notice for the Clip Detection Agent.

    This agent does not implement downstream processing. Notification is a
    durable JSON drop-file plus a structured log event that other agents or
    orchestrators can consume.
    """

    def __init__(self, queue_dir: Optional[Path] = None) -> None:
        """Create a notifier.

        Args:
            queue_dir: Optional directory for handoff queue files. When omitted,
                a ``.pipeline`` folder is created beside the recording output.
        """
        self.queue_dir = queue_dir

    def notify(self, manifest: Manifest, output_directory: Path) -> Path:
        """Emit a next-agent notification for a completed ingestion.

        Args:
            manifest: Completed recording manifest.
            output_directory: Directory containing the stored recording.

        Returns:
            Path to the written notification file.
        """
        queue = self.queue_dir or (output_directory / ".pipeline")
        queue.mkdir(parents=True, exist_ok=True)
        notice_path = queue / f"{manifest.unique_id}.notify.json"

        payload: dict[str, Any] = {
            "event": "ingestion_complete",
            "next_agent": manifest.next_agent,
            "video_id": manifest.unique_id,
            "manifest": str(output_directory / "manifest.json"),
            "output_directory": str(output_directory),
            "priority": manifest.priority,
            "game": manifest.game,
            "duration": manifest.duration,
            "checksum": manifest.checksum,
        }
        with notice_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)

        logger.info(
            "Notified next agent: %s",
            manifest.next_agent,
            extra={
                "video_id": manifest.unique_id,
                "event": "notify_next_agent",
                "output_directory": str(output_directory),
            },
        )
        return notice_path
