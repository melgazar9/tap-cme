"""CME tap class."""

from __future__ import annotations

import sys

from singer_sdk import Tap
from singer_sdk import typing as th  # JSON schema typing helpers

# TODO: Import your custom stream types here:
from tap_cme import streams

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override


class TapCME(Tap):
    """Singer tap for CME."""

    name = "tap-cme"

    # TODO: Update this section with the actual config values you expect:
    config_jsonschema = th.PropertiesList(
        th.Property(
            "client_id",
            th.StringType(nullable=False),
            required=True,
            secret=True,  # Flag config as protected.
            title="Client ID",
            description="OAuth client ID for the CME OAuth app",
        ),
        th.Property(
            "client_secret",
            th.StringType(nullable=False),
            required=True,
            secret=True,  # Flag config as protected.
            title="Client Secret",
            description="OAuth client secret for the CME OAuth app",
        ),
        th.Property(
            "refresh_token",
            th.StringType(),
            secret=True,  # Flag config as protected.
            title="Refresh Token",
            description="OAuth refresh token for the CME OAuth app",
        ),
        th.Property(
            "project_ids",
            th.ArrayType(th.StringType(nullable=False), nullable=False),
            required=True,
            title="Project IDs",
            description="Project IDs to replicate",
        ),
        th.Property(
            "api_url",
            th.StringType(nullable=False),
            title="API URL",
            default="https://api.mysample.com",
            description="The url for the API service",
        ),
    ).to_dict()

    @override
    def discover_streams(self) -> list[streams.CMEStream]:
        """Return a list of discovered streams.

        Returns:
            A list of discovered streams.
        """
        return [
            streams.GroupsStream(self),
            streams.UsersStream(self),
        ]


if __name__ == "__main__":
    TapCME.cli()
