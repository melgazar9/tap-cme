"""CME's OAuth 2.0 client-credentials grant."""

from __future__ import annotations

import sys

from singer_sdk.authenticators import OAuthAuthenticator

if sys.version_info >= (3, 12):
    from typing import override
else:
    from typing_extensions import override


class CMEAuthenticator(OAuthAuthenticator):
    """Trades the API ID and its password for a bearer token, refreshed when CME's expiry passes."""

    @override
    @property
    def oauth_request_body(self) -> dict:
        """The form CME's token endpoint takes."""
        return {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
