"""CME's trading schedules, normalized, and CME's weekly maintenance window."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from typing import Any, ClassVar
from zoneinfo import ZoneInfo


class TradingSchedule:
    """One schedule from CME's `/tradingSchedules`, checked against the keys CME sends and normalized.

    Dates become ISO dates and event times ISO UTC instants, so readers only cast. A key CME has not sent
    before, a key it no longer sends, or a date this parser cannot read stops the fetch, never a guess.
    """

    SCHEDULE_KEYS: ClassVar[frozenset[str]] = frozenset(
        {
            "_links",
            "applicableGlobexGroupCodes",
            "marketEventsByDate",
            "quadrants",
            "scheduleNames",
            "tradingScheduleId",
        }
    )
    DATE_KEYS: ClassVar[frozenset[str]] = frozenset({"marketEvents", "tradingDate"})
    EVENT_KEYS: ClassVar[frozenset[str]] = frozenset({"marketEventTime", "marketEventType", "noCancelPeriod"})
    TRADING_DATE_FORMAT: ClassVar[str] = "%m-%d-%y"
    EVENT_TIME_FORMAT: ClassVar[str] = "%m/%d/%Y %H:%M:%S.%fZ"

    @classmethod
    def normalize(cls, raw: dict[str, Any]) -> dict[str, Any]:
        """Return the schedule's record: its identity, its groups and every date's events in CME's order.

        Raises:
            ValueError: naming the schedule, the trading date and the field CME sent that this cannot read.
        """
        schedule_id = raw.get("tradingScheduleId")
        cls._require_keys(raw, cls.SCHEDULE_KEYS, f"schedule {schedule_id}")
        return {
            "trading_schedule_id": int(raw["tradingScheduleId"]),
            "applicable_globex_group_codes": list(raw["applicableGlobexGroupCodes"]),
            "quadrants": cls._labels(raw["quadrants"]),
            "schedule_names": cls._labels(raw["scheduleNames"]),
            "market_events_by_date": [cls._normalize_date(schedule_id, entry) for entry in raw["marketEventsByDate"]],
        }

    @classmethod
    def _normalize_date(cls, schedule_id: object, entry: dict[str, Any]) -> dict[str, Any]:
        where = f"schedule {schedule_id}, trading date {entry.get('tradingDate')}"
        cls._require_keys(entry, cls.DATE_KEYS, where)
        trading_date = cls._parse(entry["tradingDate"], cls.TRADING_DATE_FORMAT, where, "tradingDate").date()
        return {
            "trading_date": trading_date.isoformat(),
            "market_events": [cls._normalize_event(where, event) for event in entry["marketEvents"]],
        }

    @classmethod
    def _normalize_event(cls, where: str, event: dict[str, Any]) -> dict[str, Any]:
        cls._require_keys(event, cls.EVENT_KEYS, where)
        instant = cls._parse(event["marketEventTime"], cls.EVENT_TIME_FORMAT, where, "marketEventTime")
        return {
            "market_event_type": event["marketEventType"],
            "market_event_time": instant.replace(tzinfo=UTC).isoformat(),
            "no_cancel_period": event["noCancelPeriod"],
        }

    @staticmethod
    def _labels(found: list[str] | None) -> list[str] | None:
        """A schedule's names and quadrants, null where CME sends none (some schedules carry neither)."""
        return None if found is None else list(found)

    @staticmethod
    def _require_keys(found: dict[str, Any], expected: frozenset[str], where: str) -> None:
        unknown = sorted(set(found) - expected)
        missing = sorted(expected - set(found))
        if unknown or missing:
            msg = f"CME's response changed at {where}: unknown keys {unknown}, missing keys {missing}"
            raise ValueError(msg)

    @staticmethod
    def _parse(value: object, form: str, where: str, field: str) -> datetime:
        try:
            return datetime.strptime(str(value), form)  # noqa: DTZ007
        except ValueError as refused:
            msg = f"CME's response changed at {where}: {field} {value!r} does not read as {form!r}"
            raise ValueError(msg) from refused


class MaintenanceWindow:
    """CME's weekly maintenance, when its reference data "may be unavailable or unreliable"."""

    ZONE: ClassVar[ZoneInfo] = ZoneInfo("America/Chicago")
    START_WEEKDAY: ClassVar[int] = 4
    START: ClassVar[time] = time(22, 0)
    END_WEEKDAY: ClassVar[int] = 5
    END: ClassVar[time] = time(19, 0)

    @classmethod
    def contains(cls, instant: datetime) -> bool:
        """Whether an aware instant falls in the window, its start included and its end excluded.

        Raises:
            ValueError: for a naive instant, whose zone would be a guess.
        """
        if instant.tzinfo is None:
            msg = f"{instant} has no timezone; the maintenance window is judged in Chicago time"
            raise ValueError(msg)
        local = instant.astimezone(cls.ZONE)
        week_start = local.date() - timedelta(days=(local.weekday() - cls.START_WEEKDAY) % 7)
        opens = datetime.combine(week_start, cls.START, tzinfo=cls.ZONE)
        closes = datetime.combine(week_start + timedelta(days=cls.END_WEEKDAY - cls.START_WEEKDAY), cls.END, tzinfo=cls.ZONE)
        return opens <= local < closes
