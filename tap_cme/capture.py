"""A fetch of CME's trading schedules captured to disk, read back at its own fetch times."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from functools import cached_property
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


class CapturePages:
    """A capture folder: `manifest.json` plus `page-NNNNN.json` exactly as CME answered.

    The manifest names each page's fetch time and sha256; a page whose bytes moved, a missing page or an
    unfinished capture is refused before any record is written.
    """

    def __init__(self, folder: Path) -> None:
        """Read the capture in `folder`."""
        self.folder = folder

    @cached_property
    def manifest(self) -> dict[str, Any]:
        """The capture's manifest, refused unless the capture ran to its last page."""
        manifest = json.loads((self.folder / "manifest.json").read_text())
        if manifest.get("complete") is not True or len(manifest["pages"]) != manifest["total_pages"]:
            msg = f"capture {self.folder} is incomplete: {len(manifest['pages'])} of {manifest['total_pages']} pages"
            raise ValueError(msg)
        return manifest

    @property
    def url(self) -> str:
        """The endpoint the capture fetched."""
        return str(self.manifest["url"])

    @property
    def started_at(self) -> datetime:
        """When the capture's first request went out."""
        return datetime.fromisoformat(self.manifest["started_at_utc"])

    @property
    def completed_at(self) -> datetime:
        """When the capture's last page landed."""
        return datetime.fromisoformat(self.manifest["finished_at_utc"])

    def pages(self) -> Iterator[tuple[dict[str, Any], datetime]]:
        """Yield every page body with its fetch time, in page order, each checked against its sha256 first."""
        checked = [self._checked(entry) for entry in sorted(self.manifest["pages"], key=lambda entry: entry["page"])]
        yield from checked

    def _checked(self, entry: dict[str, Any]) -> tuple[dict[str, Any], datetime]:
        path = self.folder / f"page-{entry['page']:05d}.json"
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["sha256"]:
            msg = f"capture page {path} no longer matches its manifest sha256"
            raise ValueError(msg)
        return json.loads(raw), datetime.fromisoformat(entry["fetched_at_utc"])
