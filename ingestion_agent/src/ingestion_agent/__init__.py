"""RazTech AI Content Pipeline — Ingestion Agent.

Detects newly completed stream recordings, validates them, extracts metadata,
organizes assets, and prepares machine-readable manifests for downstream agents.

This package never edits, transcodes (beyond copy/container normalize for storage
naming), uploads videos, analyzes viral moments, or creates clips.
"""

__version__ = "1.0.0"
__pipeline_stage__ = "ingestion"

from ingestion_agent.pipeline import IngestionPipeline
from ingestion_agent.models import IngestionResult, Manifest

__all__ = [
    "IngestionPipeline",
    "IngestionResult",
    "Manifest",
    "__version__",
]
