"""One tap run's fetch of CME's trading schedules: what it asked for, what landed, and its completion record."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar

from tap_cme.schedule import MaintenanceWindow


class FetchRun:
    """Counts one fetch's pages and schedules, and summarizes the fetch once every page landed.

    The summary rides on every record the fetch writes, so a reader proves a fetch whole from its own rows: the
    distinct schedules landed must equal the `fetch_schedules` each row carries. `None` as a group stands for an
    unfiltered request (the whole of CME's schedules).
    """

    FETCH_ID_FORMAT: ClassVar[str] = "%Y%m%dT%H%M%S.%fZ"

    def __init__(self, *, source: str, requested_groups: list[str] | None, started_at: datetime) -> None:
        """Open a fetch that started at `started_at`, asking for `requested_groups` (None: every schedule)."""
        if started_at.tzinfo is None:
            msg = f"fetch start {started_at} has no timezone"
            raise ValueError(msg)
        self.source = source
        self.requested_groups = requested_groups
        self.started_at = started_at.astimezone(UTC)
        self.fetch_id = self.started_at.strftime(self.FETCH_ID_FORMAT)
        self._totals: dict[str | None, int] = {}
        self._received: dict[str | None, set[int]] = {}
        self._emitted: set[int] = set()
        self._pages = 0
        self._completed_at: datetime | None = None

    def begin_page(self, group: str | None, total: int) -> None:
        """Count a page, refusing one whose total differs from the group's first page (CME refreshed mid-fetch)."""
        known = self._totals.setdefault(group, total)
        if known != total:
            msg = f"CME's schedule count for group {group} moved from {known} to {total} during fetch {self.fetch_id}"
            raise RuntimeError(msg)
        self._received.setdefault(group, set())
        self._pages += 1

    def receive(self, group: str | None, schedule_id: int) -> None:
        """Note a schedule a group's page held."""
        self._received[group].add(schedule_id)

    def first_sight(self, schedule_id: int) -> bool:
        """Whether this fetch has not yet written the schedule (two requested groups can share one)."""
        if schedule_id in self._emitted:
            return False
        self._emitted.add(schedule_id)
        return True

    def finish(self, completed_at: datetime) -> None:
        """Close the fetch, refusing one where a requested group went unasked or fell short of its total."""
        expected = self.requested_groups if self.requested_groups is not None else [None]
        unasked = [group for group in expected if group not in self._totals]
        short = {
            group: (len(self._received[group]), total)
            for group, total in self._totals.items()
            if len(self._received[group]) != total
        }
        if unasked or short:
            msg = f"fetch {self.fetch_id} is incomplete: groups never asked {unasked}, (held, counted) by group {short}"
            raise RuntimeError(msg)
        self._completed_at = completed_at.astimezone(UTC)

    def summary(self) -> dict[str, Any]:
        """The fetch's own columns, written on each of its records.

        Raises:
            RuntimeError: when the fetch never finished, so its pages cannot be counted.
        """
        if self._completed_at is None:
            msg = f"fetch {self.fetch_id} never finished, so none of its pages may be written"
            raise RuntimeError(msg)
        return {
            "fetch_source": self.source,
            "fetch_started_at": self.started_at.isoformat(),
            "fetch_completed_at": self._completed_at.isoformat(),
            "requested_groups": self.requested_groups,
            "groups_without_schedules": sorted(group for group, total in self._totals.items() if group and total == 0),
            "fetch_schedules": len(set().union(*self._received.values())) if self._received else 0,
            "fetch_pages": self._pages,
            "fetch_in_maintenance": MaintenanceWindow.contains(self.started_at),
        }
