"""The CME tap: CME's Globex trading schedules from its Reference Data API v3."""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

from singer_sdk import Tap
from singer_sdk import typing as th

from tap_cme.capture import CapturePages
from tap_cme.fetch_run import FetchRun
from tap_cme.streams import FetchesStream, TradingSchedulesStream

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

if TYPE_CHECKING:
    from singer_sdk import Stream


class TapCME(Tap):
    """Singer tap for CME's reference data."""

    name = "tap-cme"

    config_jsonschema = th.PropertiesList(
        th.Property(
            "client_id",
            th.StringType(nullable=False),
            required=True,
            secret=True,
            title="API ID",
            description="The OAuth API ID from CME Customer Center (My Profile, APIs)",
        ),
        th.Property(
            "client_secret",
            th.StringType(nullable=False),
            required=True,
            secret=True,
            title="API password",
            description="The API ID's generated password",
        ),
        th.Property(
            "globex_group_codes",
            th.ArrayType(th.StringType(nullable=False), nullable=False),
            required=True,
            title="Globex groups",
            description="Globex group codes whose schedules each fetch asks for (one schedule can serve several groups)",
        ),
        th.Property(
            "api_url",
            th.StringType(nullable=False),
            default="https://refdata.api.cmegroup.com/refdata/v3",
            title="API URL",
            description="Reference Data API v3 root",
        ),
        th.Property(
            "auth_url",
            th.StringType(nullable=False),
            default="https://auth.cmegroup.com/as/token.oauth2",
            title="Token URL",
            description="CME's OAuth token endpoint",
        ),
        th.Property(
            "capture_dir",
            th.StringType,
            title="Capture folder",
            description="Load a fetch saved to disk (manifest.json and its pages) at its own fetch times instead of CME",
        ),
    ).to_dict()

    @cached_property
    def capture(self) -> CapturePages | None:
        """The saved fetch to load, when one is configured."""
        folder = self.config.get("capture_dir")
        return CapturePages(Path(folder)) if folder is not None else None

    @cached_property
    def fetch_run(self) -> FetchRun:
        """This run's one fetch, shared by its pages and its completion record."""
        if self.capture is not None:
            return FetchRun(
                source="capture", api_url=self.capture.url, requested_groups=None, started_at=self.capture.started_at
            )
        groups = list(self.config["globex_group_codes"])
        if not groups:
            msg = "globex_group_codes is empty: a fetch must ask for at least one Globex group"
            raise ValueError(msg)
        return FetchRun(source="api", api_url=self.config["api_url"], requested_groups=groups, started_at=datetime.now(UTC))

    @override
    def discover_streams(self) -> list[Stream]:
        return [
            TradingSchedulesStream(self, fetch_run=self.fetch_run, capture=self.capture),
            FetchesStream(self, fetch_run=self.fetch_run),
        ]


if __name__ == "__main__":
    TapCME.cli()
