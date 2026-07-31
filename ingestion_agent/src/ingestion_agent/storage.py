"""Organize recordings into the content store and failed queue."""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ingestion_agent.config import Config
from ingestion_agent.models import FailureReport, RecordingMetadata, to_iso, utc_now

logger = logging.getLogger("ingestion_agent.storage")


@dataclass
class StoreResult:
    """Paths and checksum produced when a recording is stored."""

    directory: Path
    video: Path
    hash_file: Path
    metadata: Path
    log: Path
    manifest: Path
    preview: Path
    checksum: str


def compute_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Compute the SHA-256 checksum of a file.

    Args:
        path: File to hash.
        chunk_size: Read buffer size in bytes.

    Returns:
        Hex-encoded SHA-256 digest.
    """
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def date_parts(recording_date: Optional[str] = None) -> tuple[str, str, str]:
    """Resolve YYYY, MM, DD parts for storage layout.

    Args:
        recording_date: Optional ISO date (``YYYY-MM-DD``) or compact ``YYYYMMDD``.

    Returns:
        Tuple of ``(year, month, day)``.
    """
    if recording_date:
        compact = recording_date.replace("-", "")
        if len(compact) >= 8 and compact[:8].isdigit():
            return compact[:4], compact[4:6], compact[6:8]
    now = datetime.now(timezone.utc)
    return now.strftime("%Y"), now.strftime("%m"), now.strftime("%d")


class StorageManager:
    """Move recordings into dated content directories and write artifacts."""

    def __init__(self, config: Config) -> None:
        """Create a storage manager.

        Args:
            config: Loaded agent configuration.
        """
        self.config = config
        self.filenames = config.storage_filenames()

    def output_directory(self, video_id: str, recording_date: Optional[str] = None) -> Path:
        """Return the destination directory for a video ID.

        Args:
            video_id: Unique recording ID.
            recording_date: Optional recording date for path layout.

        Returns:
            Absolute path ``{content_root}/YYYY/MM/DD/{video_id}``.
        """
        year, month, day = date_parts(recording_date)
        return self.config.content_root / year / month / day / video_id

    def store_recording(
        self,
        source: Path,
        video_id: str,
        metadata: RecordingMetadata,
        copy: bool = False,
    ) -> StoreResult:
        """Move (or copy) a recording into the content store.

        The video is stored as ``video.mp4`` per the pipeline storage contract.
        Bytes are preserved via move/copy — no re-encode is performed.

        Args:
            source: Source recording path.
            video_id: Allocated unique ID.
            metadata: Extracted metadata.
            copy: When True, copy instead of move (keeps the original).

        Returns:
            :class:`StoreResult` with artifact paths and checksum.

        Raises:
            FileExistsError: If the destination directory already exists.
            OSError: On filesystem failures.
        """
        out_dir = self.output_directory(video_id, metadata.recording_date)
        if out_dir.exists():
            raise FileExistsError(f"Output directory already exists: {out_dir}")

        out_dir.mkdir(parents=True, exist_ok=True)
        dest_video = out_dir / self.filenames["video"]

        metadata.extra["original_extension"] = source.suffix.lower()
        metadata.extra["original_filename"] = source.name

        logger.info(
            "Storing recording",
            extra={
                "path": str(source),
                "video_id": video_id,
                "output_directory": str(out_dir),
                "event": "store_begin",
            },
        )

        if copy:
            shutil.copy2(source, dest_video)
        else:
            try:
                shutil.move(str(source), str(dest_video))
            except OSError:
                shutil.copy2(source, dest_video)
                source.unlink()

        checksum = compute_sha256(dest_video)
        hash_path = out_dir / self.filenames["hash"]
        hash_path.write_text(f"sha256:{checksum}\n", encoding="utf-8")

        metadata_path = out_dir / self.filenames["metadata"]
        with metadata_path.open("w", encoding="utf-8") as fh:
            json.dump(metadata.to_dict(), fh, indent=2, default=str)

        return StoreResult(
            directory=out_dir,
            video=dest_video,
            hash_file=hash_path,
            metadata=metadata_path,
            log=out_dir / self.filenames["log"],
            manifest=out_dir / self.filenames["manifest"],
            preview=out_dir / self.filenames["preview"],
            checksum=checksum,
        )

    def write_json(self, path: Path, data: dict[str, Any]) -> Path:
        """Write a JSON document.

        Args:
            path: Destination path.
            data: JSON-serializable mapping.

        Returns:
            The written path.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, default=str)
        tmp.replace(path)
        return path

    def fail_recording(
        self,
        source: Path,
        reason: str,
        recommended_fix: str,
        details: Optional[dict[str, Any]] = None,
        move: bool = True,
    ) -> tuple[Path, FailureReport]:
        """Move a failed recording into the failed queue and write a report.

        Args:
            source: Source file that failed validation/processing.
            reason: Human-readable failure reason.
            recommended_fix: Suggested remediation.
            details: Optional structured failure details.
            move: Whether to move the source file into the failed root.

        Returns:
            Tuple of ``(failed_directory, FailureReport)``.
        """
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        safe_name = source.stem.replace(" ", "_")[:80] or "recording"
        failed_dir = self.config.failed_root / f"{stamp}_{safe_name}"
        failed_dir.mkdir(parents=True, exist_ok=True)

        dest_file = failed_dir / source.name
        if source.exists() and move:
            try:
                shutil.move(str(source), str(dest_file))
            except OSError:
                shutil.copy2(source, dest_file)
                try:
                    source.unlink()
                except OSError:
                    pass
        elif source.exists() and not move:
            shutil.copy2(source, dest_file)

        report = FailureReport(
            source_path=str(source),
            failed_at=to_iso(utc_now()) or stamp,
            reason=reason,
            recommended_fix=recommended_fix,
            details=details or {},
            log_location=str(failed_dir / self.filenames["log"]),
        )
        report_path = failed_dir / self.filenames["failure_report"]
        self.write_json(report_path, report.to_dict())

        logger.error(
            "Recording failed ingestion",
            extra={
                "path": str(source),
                "event": "failure",
                "reason": reason,
                "output_directory": str(failed_dir),
            },
        )
        return failed_dir, report
