"""The base stream for CME's Reference Data API v3."""

from __future__ import annotations

import sys
from functools import cached_property
from typing import TYPE_CHECKING

from singer_sdk.streams import RESTStream

from tap_cme.auth import CMEAuthenticator

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override

if TYPE_CHECKING:
    from singer_sdk.helpers.types import Auth


class CMEStream(RESTStream):
    """A stream of CME's Reference Data API, authorized by the tap's OAuth API ID."""

    @override
    @property
    def url_base(self) -> str:
        """The API's root, from the tap's config."""
        return str(self.config["api_url"])

    @override
    @cached_property
    def authenticator(self) -> Auth:
        """The client-credentials authenticator."""
        return CMEAuthenticator(
            client_id=self.config["client_id"],
            client_secret=self.config["client_secret"],
            auth_endpoint=self.config["auth_url"],
        )

    @override
    @property
    def http_headers(self) -> dict:
        """JSON, as CME's examples ask."""
        return {"Accept": "application/json"}
