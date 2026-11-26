"""Load custom_components/yealink_xml from this checkout in HA's test harness."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture(autouse=True)
def printer_reachable():
    """Tests never touch the network; the Online check sees a reachable printer."""
    from unittest.mock import patch

    with patch("custom_components.epson_receipt_printer.binary_sensor._can_connect", return_value=True) as check:
        yield check
