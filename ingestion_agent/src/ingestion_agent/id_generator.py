"""Unique video ID generation (RAZ-YYYYMMDD-NNN)."""

from __future__ import annotations

import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ID_PATTERN = re.compile(r"^(?P<prefix>[A-Z]+)-(?P<date>\d{8})-(?P<seq>\d{3,})$")


class IdGenerator:
    """Generate monotonically increasing, non-colliding video IDs.

    IDs follow the form ``{prefix}-{YYYYMMDD}-{seq}`` (e.g. ``RAZ-20260731-001``).
    Existing IDs under the content root are scanned so sequences never overwrite.
    """

    def __init__(self, content_root: Path, prefix: str = "RAZ") -> None:
        """Create an ID generator bound to a content root.

        Args:
            content_root: Root directory that stores ingested content by date.
            prefix: Alphabetic prefix for generated IDs.
        """
        self.content_root = Path(content_root)
        self.prefix = prefix.upper()
        self._lock = threading.Lock()
        self._reserved: set[str] = set()

    def _today(self) -> str:
        """Return today's UTC date as ``YYYYMMDD``."""
        return datetime.now(timezone.utc).strftime("%Y%m%d")

    def scan_existing(self, date_str: Optional[str] = None) -> set[str]:
        """Scan the content root for existing video IDs.

        Args:
            date_str: Optional ``YYYYMMDD`` filter. When omitted, all dates are scanned.

        Returns:
            A set of existing ID strings.
        """
        found: set[str] = set()
        if not self.content_root.exists():
            return found

        # Layout: /content/YYYY/MM/DD/<ID>/
        if date_str:
            year, month, day = date_str[:4], date_str[4:6], date_str[6:8]
            day_dir = self.content_root / year / month / day
            candidates = [day_dir] if day_dir.exists() else []
        else:
            candidates = [
                p for p in self.content_root.rglob("*") if p.is_dir() and ID_PATTERN.match(p.name)
            ]
            for path in candidates:
                found.add(path.name)
            return found

        if day_dir.exists():
            for child in day_dir.iterdir():
                if child.is_dir() and ID_PATTERN.match(child.name):
                    found.add(child.name)
        return found

    def next_sequence(self, date_str: Optional[str] = None) -> int:
        """Compute the next free sequence number for a date.

        Args:
            date_str: ``YYYYMMDD`` date string. Defaults to today (UTC).

        Returns:
            The next integer sequence (starting at 1).
        """
        date_str = date_str or self._today()
        existing = self.scan_existing(date_str) | {
            i for i in self._reserved if i.startswith(f"{self.prefix}-{date_str}-")
        }
        max_seq = 0
        for video_id in existing:
            match = ID_PATTERN.match(video_id)
            if match and match.group("date") == date_str and match.group("prefix") == self.prefix:
                max_seq = max(max_seq, int(match.group("seq")))
        return max_seq + 1

    def generate(self, date_str: Optional[str] = None) -> str:
        """Generate and reserve a new unique video ID.

        Args:
            date_str: Optional ``YYYYMMDD`` override. Defaults to today (UTC).

        Returns:
            A unique ID such as ``RAZ-20260731-001``.
        """
        with self._lock:
            date_str = date_str or self._today()
            seq = self.next_sequence(date_str)
            while True:
                video_id = f"{self.prefix}-{date_str}-{seq:03d}"
                if video_id not in self._reserved and video_id not in self.scan_existing(date_str):
                    self._reserved.add(video_id)
                    return video_id
                seq += 1

    def release(self, video_id: str) -> None:
        """Release a previously reserved ID (e.g. after a failed allocation).

        Args:
            video_id: The ID to release from the in-memory reservation set.
        """
        with self._lock:
            self._reserved.discard(video_id)
