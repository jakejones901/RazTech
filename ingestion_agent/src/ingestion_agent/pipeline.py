"""Orchestrates end-to-end ingestion of a single recording."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Optional

from ingestion_agent.config import Config, load_config
from ingestion_agent.content_prep import ContentPreparer
from ingestion_agent.id_generator import IdGenerator
from ingestion_agent.logging_setup import ProcessingLogHandler, get_logger, log_event, setup_logging
from ingestion_agent.manifest import ManifestBuilder
from ingestion_agent.metadata import MetadataExtractor
from ingestion_agent.models import IngestionResult, ProcessingStatus
from ingestion_agent.notifier import NextAgentNotifier
from ingestion_agent.storage import StorageManager
from ingestion_agent.stream_detection import StreamDetector
from ingestion_agent.validator import RecordingValidator
from ingestion_agent.watcher import RecordingWatcher

logger = get_logger("ingestion_agent.pipeline")


def recommended_fix_for(reason: str) -> str:
    """Map a failure reason to a practical remediation hint.

    Args:
        reason: Failure reason text.

    Returns:
        Recommended fix string.
    """
    lower = reason.lower()
    if "still being written" in lower or "unchanged" in lower:
        return "Wait for the recorder to finish, then re-import the file."
    if "could not be opened" in lower or "ffprobe" in lower or "corrupt" in lower:
        return "Re-export or re-record the video; ensure the container is not truncated."
    if "duration" in lower:
        return "Provide a recording longer than the configured minimum duration (> 2 minutes)."
    if "no video stream" in lower:
        return "Ensure the file contains a video track and is not audio-only."
    if "no audio stream" in lower:
        return "Ensure the recording includes an audio track, or relax require_audio_stream."
    if "extension" in lower:
        return "Convert the file to mp4, mkv, mov, or avi."
    if "empty" in lower:
        return "Discard the empty file and verify disk space / recorder settings."
    return "Inspect failure_report.json and processing.log, then re-submit a valid recording."


class IngestionPipeline:
    """First-stage pipeline agent: validate, enrich, store, and hand off."""

    def __init__(self, config: Optional[Config] = None) -> None:
        """Create a pipeline instance.

        Args:
            config: Optional preloaded configuration. Loads defaults when omitted.
        """
        self.config = config or load_config()
        self.validator = RecordingValidator(self.config)
        detection_cfg = self.config.stream_detection()
        self.detector = StreamDetector(
            known_games=list(detection_cfg.get("known_games") or []),
            streaming_software=list(detection_cfg.get("streaming_software") or []),
            platforms=list(detection_cfg.get("platforms") or []),
        )
        self.metadata_extractor = MetadataExtractor(
            known_games=list(detection_cfg.get("known_games") or [])
        )
        self.content_preparer = ContentPreparer(self.config)
        self.storage = StorageManager(self.config)
        self.ids = IdGenerator(self.config.content_root, prefix=self.config.id_prefix)
        self.manifests = ManifestBuilder(self.config)
        self.notifier = NextAgentNotifier()
        self._semaphore = asyncio.Semaphore(self.config.max_concurrent)

    async def process_file(
        self,
        path: Path,
        *,
        skip_stability: bool = False,
        copy: bool = False,
        move_on_failure: bool = True,
    ) -> IngestionResult:
        """Ingest a single recording end-to-end.

        Args:
            path: Path to the candidate recording.
            skip_stability: Skip size-stability wait (testing / already-stable files).
            copy: Copy into content store instead of moving.
            move_on_failure: Move failed sources into the failed root.

        Returns:
            :class:`IngestionResult` describing success or failure.
        """
        async with self._semaphore:
            return await self._process_file_inner(
                Path(path),
                skip_stability=skip_stability,
                copy=copy,
                move_on_failure=move_on_failure,
            )

    async def _process_file_inner(
        self,
        path: Path,
        *,
        skip_stability: bool,
        copy: bool,
        move_on_failure: bool,
    ) -> IngestionResult:
        started = time.perf_counter()
        detection_time = time.time()
        proc_handler = ProcessingLogHandler()
        pipeline_logger = logging.getLogger("ingestion_agent")
        pipeline_logger.addHandler(proc_handler)

        video_id: Optional[str] = None
        log_location: Optional[str] = None

        try:
            log_event(
                logger,
                "Processing started",
                path=str(path),
                event="process_start",
            )

            validation = await self.validator.validate(path, skip_stability=skip_stability)
            if not validation.ok:
                reason = "; ".join(validation.reasons) or "Validation failed"
                fix = recommended_fix_for(reason)
                failed_dir, report = self.storage.fail_recording(
                    path,
                    reason=reason,
                    recommended_fix=fix,
                    details={"validation": validation.to_dict()},
                    move=move_on_failure,
                )
                log_location = report.log_location
                proc_handler.write_to(failed_dir / self.config.storage_filenames()["log"])
                return IngestionResult(
                    success=False,
                    reason=reason,
                    recommended_fix=fix,
                    log_location=log_location,
                )

            probe_tags = (validation.probe_data.get("format") or {}).get("tags") or {}
            probe_tags = dict(probe_tags)
            probe_tags["_duration"] = validation.duration_seconds

            stream_info = self.detector.detect(path, probe_tags=probe_tags)
            metadata = self.metadata_extractor.extract(path, validation, stream_info=stream_info)

            video_id = self.ids.generate(
                date_str=(metadata.recording_date or "").replace("-", "") or None
            )

            store = self.storage.store_recording(path, video_id, metadata, copy=copy)
            log_location = str(store.log)

            # Refresh file_path to stored location for metadata consistency.
            metadata.file_path = str(store.video)
            self.storage.write_json(store.metadata, metadata.to_dict())

            placeholders = await self.content_preparer.prepare(
                store.video, store.directory, metadata
            )
            _ = placeholders  # persisted by ContentPreparer

            manifest = self.manifests.build(
                video_id=video_id,
                metadata=metadata,
                checksum=store.checksum,
                output_directory=store.directory,
                metadata_path=store.metadata,
                content_prep_path=store.directory / "content_prep.json",
                status=ProcessingStatus.READY,
            )
            self.manifests.write(manifest, store.manifest)

            if self.config.get("processing", "notify_on_complete", default=True):
                self.notifier.notify(manifest, store.directory)

            elapsed_ms = int((time.perf_counter() - started) * 1000)
            log_event(
                logger,
                "Processing complete",
                video_id=video_id,
                path=str(store.video),
                event="process_complete",
                duration_ms=elapsed_ms,
                output_directory=str(store.directory),
            )
            # Also record detection time for the processing log contract.
            log_event(
                logger,
                "Detection time recorded",
                video_id=video_id,
                event="detection_time",
                duration_ms=int(detection_time * 1000),
            )
            proc_handler.write_to(store.log)

            return IngestionResult(
                success=True,
                video_id=video_id,
                duration=manifest.duration,
                game=manifest.game,
                output_directory=str(store.directory),
                manifest_location=str(store.manifest),
                next_agent=manifest.next_agent,
                log_location=str(store.log),
            )

        except Exception as exc:  # noqa: BLE001 — top-level guard for one file
            logger.exception(
                "Unhandled ingestion error",
                extra={"path": str(path), "event": "process_error", "reason": str(exc)},
            )
            if video_id:
                self.ids.release(video_id)
            reason = f"Processing error: {exc}"
            fix = recommended_fix_for(reason)
            try:
                failed_dir, report = self.storage.fail_recording(
                    path,
                    reason=reason,
                    recommended_fix=fix,
                    details={"exception": str(exc)},
                    move=move_on_failure and path.exists(),
                )
                log_location = report.log_location
                proc_handler.write_to(failed_dir / self.config.storage_filenames()["log"])
            except Exception as nested:  # noqa: BLE001
                log_location = log_location or str(nested)
            return IngestionResult(
                success=False,
                video_id=video_id,
                reason=reason,
                recommended_fix=fix,
                log_location=log_location,
            )
        finally:
            pipeline_logger.removeHandler(proc_handler)

    async def watch_forever(self, stop_event: Optional[asyncio.Event] = None) -> None:
        """Run the directory watcher until stopped.

        Args:
            stop_event: Optional asyncio event used to signal shutdown.
        """
        # Ensure roots exist so Docker volume mounts are ready.
        for directory in self.config.watch_directories:
            directory.mkdir(parents=True, exist_ok=True)
        self.config.content_root.mkdir(parents=True, exist_ok=True)
        self.config.failed_root.mkdir(parents=True, exist_ok=True)

        async def _handle(path: Path) -> None:
            result = await self.process_file(path)
            print(result.format_output(), flush=True)

        watcher = RecordingWatcher(self.config, on_detected=_handle)
        await watcher.run(stop_event=stop_event)


def create_pipeline(config_path: Optional[str] = None) -> IngestionPipeline:
    """Factory that loads configuration and constructs a pipeline.

    Args:
        config_path: Optional path to a YAML config override.

    Returns:
        Ready :class:`IngestionPipeline`.
    """
    config = load_config(config_path)
    setup_logging(
        level=str(config.get("logging", "level", default="INFO")),
        fmt=str(config.get("logging", "format", default="json")),
        console=bool(config.get("logging", "console", default=True)),
        log_file=config.get("logging", "file", default=None),
    )
    return IngestionPipeline(config)
