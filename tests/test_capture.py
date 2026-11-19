"""Loading a fetch saved to disk at its own fetch times, and refusing one that is incomplete or altered."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from tap_cme.tap import TapCME

FIXTURE = Path(__file__).parent / "fixtures" / "treasury_schedule_page.json"
STARTED = "2026-11-19T19:47:54.387559+00:00"
FINISHED = "2026-11-19T19:51:53.000304+00:00"
PAGE_TIMES = ["2026-11-19T19:47:55.100000+00:00", "2026-11-19T19:47:56.200000+00:00"]


def write_capture(folder: Path, *, complete: bool = True) -> Path:
    """A two-page capture of two schedules, as the capture script writes it."""
    folder.mkdir()
    pages = []
    for number, fetched_at in enumerate(PAGE_TIMES):
        body = json.loads(FIXTURE.read_text())
        body["_embedded"]["tradingSchedules"][0]["tradingScheduleId"] = 1000 + number
        body["page"] = {"size": 1, "totalElements": 2, "totalPages": 2, "number": number}
        raw = json.dumps(body).encode()
        (folder / f"page-{number:05d}.json").write_bytes(raw)
        pages.append(
            {
                "page": number,
                "fetched_at_utc": fetched_at,
                "status": 200,
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    manifest = {
        "url": "https://refdata.api.cmegroup.com/refdata/v3/tradingSchedules",
        "size": 1,
        "started_at_utc": STARTED,
        "finished_at_utc": FINISHED,
        "total_pages": 2,
        "complete": complete,
        "pages": pages,
    }
    (folder / "manifest.json").write_text(json.dumps(manifest))
    return folder


def capture_config(folder: Path) -> dict[str, Any]:
    return {"client_id": "API_TEST", "client_secret": "secret", "globex_group_codes": ["ZN"], "capture_dir": str(folder)}


def records(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    messages = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    return [m for m in messages if m["type"] == "RECORD"]


def test_capture_loads_at_its_own_fetch_times(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    TapCME(config=capture_config(write_capture(tmp_path / "capture"))).sync_all()
    written = records(capsys)
    assert [r["stream"] for r in written] == ["trading_schedules", "trading_schedules", "trading_schedules_fetches"]
    schedules, fetch = [r["record"] for r in written[:2]], written[2]["record"]
    assert [s["trading_schedule_id"] for s in schedules] == [1000, 1001]
    assert [s["fetched_at"] for s in schedules] == PAGE_TIMES
    assert fetch["source"] == "capture"
    assert fetch["requested_groups"] is None
    assert fetch["groups_without_schedules"] == []
    assert fetch["schedules"] == 2
    assert fetch["started_at"] == STARTED
    assert fetch["completed_at"] == FINISHED
    assert fetch["fetch_id"] == "20261119T194754.387559Z"
    assert {s["fetch_id"] for s in schedules} == {fetch["fetch_id"]}


def test_a_tampered_capture_page_is_refused(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    folder = write_capture(tmp_path / "capture")
    page = folder / "page-00001.json"
    page.write_bytes(page.read_bytes().replace(b"1001", b"1002"))
    with pytest.raises(ValueError, match=r"page-00001\.json"):
        TapCME(config=capture_config(folder)).sync_all()
    assert records(capsys) == []


def test_an_incomplete_capture_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="incomplete"):
        TapCME(config=capture_config(write_capture(tmp_path / "capture", complete=False))).sync_all()
