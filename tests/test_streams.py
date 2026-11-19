"""The tap against a mocked CME: token, pages, the fetch's completion record and its refusals."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs

import pytest

from tap_cme.fetch_run import FetchRun
from tap_cme.tap import TapCME

if TYPE_CHECKING:
    import requests_mock as rm

FIXTURE = Path(__file__).parent / "fixtures" / "treasury_schedule_page.json"
API = "https://refdata.api.cmegroup.com/refdata/v3"
SCHEDULES = f"{API}/tradingSchedules"
TOKEN = "https://auth.cmegroup.com/as/token.oauth2"
CONFIG = {"client_id": "API_TEST", "client_secret": "secret", "globex_group_codes": ["ZN"]}


def schedule(schedule_id: int) -> dict[str, Any]:
    raw = copy.deepcopy(json.loads(FIXTURE.read_text())["_embedded"]["tradingSchedules"][0])
    raw["tradingScheduleId"] = schedule_id
    return raw


def page(schedules: list[dict[str, Any]], number: int, total: int) -> dict[str, Any]:
    body: dict[str, Any] = {"_links": {}, "page": {"size": 1, "totalElements": total, "totalPages": total, "number": number}}
    if schedules:
        body["_embedded"] = {"tradingSchedules": schedules}
    return body


def answer(requests_mock: rm.Mocker, group: str, pages: list[dict[str, Any] | int]) -> None:
    """Mock one group's pages in order; an int answers that HTTP status instead of a page."""
    by_number: dict[int, list[dict[str, Any]]] = {}
    number = 0
    for reply in pages:
        by_number.setdefault(number, []).append(
            {"status_code": reply} if isinstance(reply, int) else {"json": reply, "status_code": 200}
        )
        if not isinstance(reply, int):
            number += 1
    for page_number, replies in by_number.items():
        requests_mock.get(f"{SCHEDULES}?globexGroupCode={group}&page={page_number}&size=1", replies, complete_qs=True)


@pytest.fixture
def cme(requests_mock: rm.Mocker) -> rm.Mocker:
    requests_mock.post(TOKEN, json={"access_token": "t", "token_type": "Bearer", "expires_in": 1799})
    return requests_mock


def written(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    """The RECORD messages the tap wrote, in order."""
    messages = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    return [m for m in messages if m["type"] == "RECORD"]


def run(capsys: pytest.CaptureFixture[str], config: dict[str, Any], catalog: dict | None = None) -> list[dict[str, Any]]:
    """Sync the tap and return its RECORD messages in the order written."""
    TapCME(config=config, catalog=catalog).sync_all()
    return written(capsys)


def test_one_group_one_page(cme: rm.Mocker, capsys: pytest.CaptureFixture[str]) -> None:
    answer(cme, "ZN", [page([schedule(260961)], 0, 1)])
    records = run(capsys, CONFIG)
    assert [r["stream"] for r in records] == ["trading_schedules", "trading_schedules_fetches"]
    schedule_record, fetch = records[0]["record"], records[1]["record"]
    assert schedule_record["trading_schedule_id"] == 260961
    assert schedule_record["fetch_id"] == fetch["fetch_id"]
    assert fetch["schedules"] == 1
    assert fetch["pages"] == 1
    assert fetch["requested_groups"] == ["ZN"]
    assert fetch["groups_without_schedules"] == []
    assert fetch["source"] == "api"
    assert fetch["in_maintenance"] is False
    token_request, schedule_request = cme.request_history[0], cme.request_history[1]
    assert parse_qs(token_request.text) == {
        "grant_type": ["client_credentials"],
        "client_id": ["API_TEST"],
        "client_secret": ["secret"],
    }
    assert schedule_request.headers["Authorization"] == "Bearer t"


def test_pages_until_total_pages(cme: rm.Mocker, capsys: pytest.CaptureFixture[str]) -> None:
    answer(cme, "ZN", [page([schedule(n)], n - 1, 3) for n in (1, 2, 3)])
    records = run(capsys, CONFIG)
    assert [r["record"]["trading_schedule_id"] for r in records if r["stream"] == "trading_schedules"] == [1, 2, 3]
    assert records[-1]["record"]["pages"] == 3


def test_a_changing_total_stops_the_fetch(cme: rm.Mocker, capsys: pytest.CaptureFixture[str]) -> None:
    answer(cme, "ZN", [page([schedule(1)], 0, 2), page([schedule(2)], 1, 3)])
    with pytest.raises(RuntimeError, match="moved from 2 to 3"):
        TapCME(config=CONFIG).sync_all()
    assert "trading_schedules_fetches" not in [r["stream"] for r in written(capsys)]


def test_a_schedule_two_groups_share_is_one_record(cme: rm.Mocker, capsys: pytest.CaptureFixture[str]) -> None:
    answer(cme, "ZN", [page([schedule(260961)], 0, 1)])
    answer(cme, "ZB", [page([schedule(260961)], 0, 1)])
    records = run(capsys, {**CONFIG, "globex_group_codes": ["ZN", "ZB"]})
    assert [r["stream"] for r in records] == ["trading_schedules", "trading_schedules_fetches"]
    assert records[-1]["record"]["schedules"] == 1
    assert records[-1]["record"]["pages"] == 2


def test_an_empty_group_is_listed(cme: rm.Mocker, capsys: pytest.CaptureFixture[str]) -> None:
    answer(cme, "ZN", [page([schedule(260961)], 0, 1)])
    answer(cme, "XX", [page([], 0, 0)])
    records = run(capsys, {**CONFIG, "globex_group_codes": ["ZN", "XX"]})
    assert records[-1]["record"]["groups_without_schedules"] == ["XX"]
    assert records[-1]["record"]["schedules"] == 1


def test_schedules_missing_from_a_counted_page_are_refused(cme: rm.Mocker) -> None:
    answer(cme, "ZN", [page([], 0, 1)])
    with pytest.raises(RuntimeError, match="counts 1 schedules but holds none"):
        TapCME(config=CONFIG).sync_all()


def test_fetches_refuses_without_its_pages(cme: rm.Mocker) -> None:
    catalog = TapCME(config=CONFIG).catalog_dict
    for entry in catalog["streams"]:
        if entry["tap_stream_id"] == "trading_schedules":
            for metadata in entry["metadata"]:
                if metadata["breadcrumb"] == []:
                    metadata["metadata"]["selected"] = False
    with pytest.raises(RuntimeError, match="trading_schedules"):
        TapCME(config=CONFIG, catalog=catalog).sync_all()
    assert not [r for r in cme.request_history if r.url.startswith(SCHEDULES)]


def test_maintenance_fetch_is_flagged() -> None:
    started = datetime(2026, 11, 21, 18, 0, tzinfo=UTC)
    fetch = FetchRun(source="api", api_url=API, requested_groups=["ZN"], started_at=started)
    fetch.begin_page("ZN", 0)
    fetch.finish(started)
    assert fetch.record()["in_maintenance"] is True


def test_a_429_is_retried(cme: rm.Mocker, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("time.sleep", lambda _seconds: None)
    answer(cme, "ZN", [429, page([schedule(260961)], 0, 1)])
    records = run(capsys, CONFIG)
    assert [r["stream"] for r in records] == ["trading_schedules", "trading_schedules_fetches"]
