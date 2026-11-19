"""The SDK's standard tap tests against CME itself, run only where an API ID is set."""

from __future__ import annotations

import os

import pytest
from singer_sdk.testing import get_tap_test_class

from tap_cme.tap import TapCME

LIVE_CONFIG = {
    "client_id": os.environ.get("CME_API_ID", ""),
    "client_secret": os.environ.get("CME_API_PASSWORD", ""),
    "globex_group_codes": ["ZN"],
}

TestTapCME = pytest.mark.skipif(not os.environ.get("CME_API_ID"), reason="CME_API_ID not set: no live CME tests")(
    get_tap_test_class(tap_class=TapCME, config=LIVE_CONFIG)
)
