"""CME's trading schedules, one record per schedule per fetch, each carrying its fetch's summary."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import parse_qs, urlparse

from singer_sdk import typing as th
from singer_sdk.pagination import PageNumberPaginator

from tap_cme.client import CMEStream
from tap_cme.schedule import TradingSchedule

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

    import requests
    from singer_sdk import Tap
    from singer_sdk.helpers.types import Context

    from tap_cme.capture import CapturePages
    from tap_cme.fetch_run import FetchRun


class SchedulePagePaginator(PageNumberPaginator):
    """Page numbers until CME's own page count, never its `next` links (a filtered link may drop its filter)."""

    @override
    def has_more(self, response: requests.Response) -> bool:
        page = response.json()["page"]
        return int(page["number"]) + 1 < int(page["totalPages"])


class TradingSchedulesStream(CMEStream):
    """One record per schedule per fetch: every trading date's market events, as CME publishes them.

    A fetch's pages are held until its last one lands, then written with the fetch's summary, so a fetch that
    fails part-way writes nothing and a reader proves a fetch whole from its own rows.
    """

    name = "trading_schedules"
    path = "/tradingSchedules"
    primary_keys = ("fetch_id", "trading_schedule_id")
    replication_key = None
    # one schedule a page: a page past CME's 10 MB response cap answers 502
    PAGE_SIZE: ClassVar[int] = 1
    GROUP_PARAM: ClassVar[str] = "globexGroupCode"

    schema = th.PropertiesList(
        th.Property("fetch_id", th.StringType, required=True),
        th.Property("fetched_at", th.DateTimeType, required=True, description="When this schedule's page landed"),
        th.Property("trading_schedule_id", th.IntegerType, required=True, description="Not stable across fetches"),
        th.Property("applicable_globex_group_codes", th.ArrayType(th.StringType)),
        th.Property("quadrants", th.ArrayType(th.StringType)),
        th.Property("schedule_names", th.ArrayType(th.StringType)),
        th.Property(
            "market_events_by_date",
            th.ArrayType(
                th.ObjectType(
                    th.Property("trading_date", th.DateType),
                    th.Property(
                        "market_events",
                        th.ArrayType(
                            th.ObjectType(
                                th.Property("market_event_type", th.StringType),
                                th.Property("market_event_time", th.DateTimeType),
                                th.Property("no_cancel_period", th.StringType),
                            )
                        ),
                    ),
                )
            ),
        ),
        th.Property("fetch_source", th.StringType, required=True, description="api, or capture for a fetch saved to disk"),
        th.Property("fetch_started_at", th.DateTimeType, required=True),
        th.Property("fetch_completed_at", th.DateTimeType, required=True),
        th.Property(
            "requested_groups",
            th.ArrayType(th.StringType),
            description="Globex groups the fetch asked for; null for an unfiltered fetch of every schedule",
        ),
        th.Property("groups_without_schedules", th.ArrayType(th.StringType), description="Asked for, none answered"),
        th.Property("fetch_schedules", th.IntegerType, required=True, description="Distinct schedules the fetch landed"),
        th.Property("fetch_pages", th.IntegerType, required=True),
        th.Property(
            "fetch_in_maintenance", th.BooleanType, required=True, description="Started inside CME's weekly maintenance"
        ),
    ).to_dict()

    def __init__(self, tap: Tap, *, fetch_run: FetchRun, capture: CapturePages | None) -> None:
        """Serve `fetch_run`, from CME or from `capture` when one is given."""
        super().__init__(tap)
        self.fetch_run = fetch_run
        self.capture = capture

    @override
    def get_records(self, context: Context | None) -> Iterable[dict[str, Any]]:
        """Every page of the fetch, held until the last lands, then each schedule once with the fetch's summary."""
        landed = list(self._captured() if self.capture is not None else self._requested())
        summary = self.fetch_run.summary()
        for record in landed:
            if self.fetch_run.first_sight(record["trading_schedule_id"]):
                yield {**record, **summary}

    def _captured(self) -> Iterator[dict[str, Any]]:
        if self.capture is None:
            msg = "no capture configured"
            raise ValueError(msg)
        for body, fetched_at in self.capture.pages():
            yield from self._page_records(None, body, fetched_at)
        self.fetch_run.finish(self.capture.completed_at)

    def _requested(self) -> Iterator[dict[str, Any]]:
        for group in self.fetch_run.requested_groups or []:
            yield from self.request_records({"globex_group": group})
        self.fetch_run.finish(datetime.now(UTC))

    @override
    def get_new_paginator(self) -> SchedulePagePaginator:
        return SchedulePagePaginator(start_value=0)

    @override
    def get_url_params(self, context: Context | None, next_page_token: Any | None) -> dict[str, Any]:
        if context is None:
            msg = "a trading-schedules request needs its Globex group"
            raise ValueError(msg)
        return {self.GROUP_PARAM: context["globex_group"], "page": next_page_token, "size": self.PAGE_SIZE}

    @override
    def parse_response(self, response: requests.Response) -> Iterable[dict[str, Any]]:
        group = parse_qs(urlparse(str(response.request.url)).query)[self.GROUP_PARAM][0]
        yield from self._page_records(group, response.json(), datetime.now(UTC))

    def _page_records(self, group: str | None, body: dict[str, Any], fetched_at: datetime) -> Iterator[dict[str, Any]]:
        total = int(body["page"]["totalElements"])
        self.fetch_run.begin_page(group, total)
        schedules = body.get("_embedded", {}).get("tradingSchedules", [])
        if total and not schedules:
            msg = f"CME's page {body['page']['number']} for group {group} counts {total} schedules but holds none"
            raise RuntimeError(msg)
        for raw in schedules:
            schedule = TradingSchedule.normalize(raw)
            self.fetch_run.receive(group, schedule["trading_schedule_id"])
            yield {"fetch_id": self.fetch_run.fetch_id, "fetched_at": fetched_at.isoformat(), **schedule}
