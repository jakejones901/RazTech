"""Manifest creation for downstream pipeline handoff."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from ingestion_agent.config import Config
from ingestion_agent.models import Manifest, ProcessingStatus, RecordingMetadata


class ManifestBuilder:
    """Build and persist machine-readable ingestion manifests."""

    def __init__(self, config: Config) -> None:
        """Create a manifest builder.

        Args:
            config: Loaded agent configuration.
        """
        self.config = config

    def build(
        self,
        video_id: str,
        metadata: RecordingMetadata,
        checksum: str,
        output_directory: Path,
        metadata_path: Optional[Path] = None,
        content_prep_path: Optional[Path] = None,
        status: ProcessingStatus = ProcessingStatus.READY,
    ) -> Manifest:
        """Construct a :class:`Manifest` for a successfully ingested recording.

        Args:
            video_id: Unique recording ID.
            metadata: Extracted metadata.
            checksum: Hex SHA-256 of the stored video.
            output_directory: Content store directory.
            metadata_path: Optional path to metadata.json.
            content_prep_path: Optional path to content_prep.json.
            status: Pipeline status value.

        Returns:
            Populated :class:`Manifest`.
        """
        filenames = self.config.storage_filenames()
        return Manifest(
            unique_id=video_id,
            video_filename=filenames["video"],
            original_location=metadata.file_path,
            duration=float(metadata.duration_seconds or 0.0),
            game=metadata.game_title,
            recording_date=metadata.recording_date,
            creator=self.config.creator,
            project=self.config.project,
            status=status.value,
            pipeline_version=self.config.pipeline_version,
            checksum=f"sha256:{checksum}",
            next_agent=self.config.next_agent,
            priority=self.config.priority,
            tags=list(metadata.tags),
            output_directory=str(output_directory),
            metadata_path=str(metadata_path) if metadata_path else None,
            content_prep_path=str(content_prep_path) if content_prep_path else None,
        )

    def write(self, manifest: Manifest, path: Path) -> Path:
        """Serialize a manifest to disk.

        Args:
            manifest: Manifest instance.
            path: Destination JSON path.

        Returns:
            The written path.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            json.dump(manifest.to_dict(), fh, indent=2)
        return path
