"""Normalizing CME's trading schedules and judging CME's weekly maintenance window."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from tap_cme.schedule import MaintenanceWindow, TradingSchedule

FIXTURE = Path(__file__).parent / "fixtures" / "treasury_schedule_page.json"
CT = ZoneInfo("America/Chicago")


@pytest.fixture
def raw_schedule() -> dict:
    return json.loads(FIXTURE.read_text())["_embedded"]["tradingSchedules"][0]


def events_on(schedule: dict, trading_date: str) -> list[dict]:
    entry = next(d for d in schedule["market_events_by_date"] if d["trading_date"] == trading_date)
    return entry["market_events"]


def test_good_friday_closes_at_1015_ct(raw_schedule: dict) -> None:
    schedule = TradingSchedule.normalize(raw_schedule)
    close = events_on(schedule, "2026-04-03")[-1]
    assert close["market_event_type"] == "closed"
    assert close["market_event_time"] == "2026-04-03T15:15:00+00:00"


def test_juneteenth_session_is_filed_under_monday(raw_schedule: dict) -> None:
    events = events_on(TradingSchedule.normalize(raw_schedule), "2026-06-22")
    assert [e["market_event_type"] for e in events] == [
        "preopen",
        "open",
        "closed",
        "open",
        "closed",
        "preopen",
        "open",
        "closed",
    ]
    assert events[2]["market_event_time"] == "2026-06-19T17:00:00+00:00"


def test_events_keep_cme_order_and_no_cancel_verbatim(raw_schedule: dict) -> None:
    schedule = TradingSchedule.normalize(raw_schedule)
    events = events_on(schedule, "2026-11-18")
    assert [e["no_cancel_period"] for e in events] == ["description:30", None, None]
    assert [e["market_event_time"] for e in events] == [
        "2026-11-17T22:45:00+00:00",
        "2026-11-17T23:00:00+00:00",
        "2026-11-18T22:00:00+00:00",
    ]
    assert schedule["trading_schedule_id"] == 260961
    assert "ZN" in schedule["applicable_globex_group_codes"]
    assert schedule["schedule_names"] == ["INTEREST RATES/TREASURIES SC"]
    assert schedule["quadrants"] == ["IR & TREASURY"]
    assert set(schedule) == {
        "trading_schedule_id",
        "applicable_globex_group_codes",
        "quadrants",
        "schedule_names",
        "market_events_by_date",
    }


def test_null_names_and_quadrants_stay_null(raw_schedule: dict) -> None:
    changed = copy.deepcopy(raw_schedule)
    changed["quadrants"] = None
    changed["scheduleNames"] = None
    schedule = TradingSchedule.normalize(changed)
    assert schedule["quadrants"] is None
    assert schedule["schedule_names"] is None


def test_an_unknown_key_is_refused(raw_schedule: dict) -> None:
    changed = copy.deepcopy(raw_schedule)
    entry = next(d for d in changed["marketEventsByDate"] if d["tradingDate"] == "11-18-26")
    entry["marketEvents"][0]["newField"] = 1
    with pytest.raises(ValueError, match="newField") as refused:
        TradingSchedule.normalize(changed)
    assert "260961" in str(refused.value)
    assert "11-18-26" in str(refused.value)


def test_a_missing_key_is_refused(raw_schedule: dict) -> None:
    changed = copy.deepcopy(raw_schedule)
    del changed["scheduleNames"]
    with pytest.raises(ValueError, match="scheduleNames"):
        TradingSchedule.normalize(changed)


def test_an_unparsable_time_is_refused(raw_schedule: dict) -> None:
    changed = copy.deepcopy(raw_schedule)
    entry = next(d for d in changed["marketEventsByDate"] if d["tradingDate"] == "11-18-26")
    entry["marketEvents"][2]["marketEventTime"] = "2026-11-18T22:00:00Z"
    with pytest.raises(ValueError, match="marketEventTime") as refused:
        TradingSchedule.normalize(changed)
    assert "11-18-26" in str(refused.value)


def test_an_unparsable_trading_date_is_refused(raw_schedule: dict) -> None:
    changed = copy.deepcopy(raw_schedule)
    changed["marketEventsByDate"][0]["tradingDate"] = "2026-04-03"
    with pytest.raises(ValueError, match="tradingDate"):
        TradingSchedule.normalize(changed)


@pytest.mark.parametrize(
    ("instant", "inside"),
    [
        (datetime(2026, 11, 20, 22, 0, tzinfo=CT), True),
        (datetime(2026, 11, 21, 18, 59, tzinfo=CT), True),
        (datetime(2026, 11, 20, 21, 59, tzinfo=CT), False),
        (datetime(2026, 11, 21, 19, 0, tzinfo=CT), False),
        (datetime(2026, 11, 21, 4, 0, tzinfo=UTC), True),
        (datetime(2026, 7, 11, 2, 59, tzinfo=UTC), False),
        (datetime(2026, 7, 11, 3, 0, tzinfo=UTC), True),
    ],
)
def test_maintenance_window_bounds(instant: datetime, inside: bool) -> None:
    assert MaintenanceWindow.contains(instant) is inside


def test_maintenance_window_refuses_a_naive_instant() -> None:
    with pytest.raises(ValueError, match="timezone"):
        MaintenanceWindow.contains(datetime(2026, 11, 20, 22, 0))  # noqa: DTZ001
