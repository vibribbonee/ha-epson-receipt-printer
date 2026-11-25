"""Receipt bytes and the services that build them."""
from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.epson_receipt_printer import escpos
from custom_components.epson_receipt_printer.const import DOMAIN


def test_euro_and_accents_print_instead_of_question_marks():
    data = escpos._text("Kaas €3,50 · café\n")
    assert b"?" not in data
    assert data == "Kaas €3,50 · café\n".encode("cp858")


def test_typographic_punctuation_is_simplified():
    assert escpos._text("Bob’s “best” – tea…") == b"Bob's \"best\" - tea..."


def test_every_job_selects_the_euro_code_page():
    receipt = escpos.build_blocks_receipt(
        [{"type": "text", "text": "€", "alignment": "left", "text_size": "normal",
          "bold": False, "underline": False, "font": "A"}]
    )
    assert receipt.startswith(b"\x1b@\x1bt\x13")
    assert escpos.build_shopping_receipt("Shop", ["Milk"]).startswith(b"\x1b@\x1bt\x13")


@pytest.fixture
async def entry(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="192.168.0.20:9100", title="Receipts",
        data={"name": "Receipts", "host": "192.168.0.20", "port": 9100},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_missing_image_is_a_clear_validation_error(hass, entry):
    with pytest.raises(ServiceValidationError, match="could not read missing.png"):
        await hass.services.async_call(
            DOMAIN, "print_text",
            {"config_entry_id": entry.entry_id,
             "blocks": [{"type": "image", "image_path": "missing.png"}]},
            blocking=True,
        )


async def test_reconfigure_moves_the_printer_to_its_new_address(hass, entry):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    assert result["step_id"] == "reconfigure"
    with patch(
        "custom_components.epson_receipt_printer.config_flow._can_connect", return_value=True
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "192.168.0.45", "port": 9100}
        )
    assert result["reason"] == "reconfigure_successful"
    assert entry.data["host"] == "192.168.0.45"
    assert entry.data["name"] == "Receipts"
    assert entry.unique_id == "192.168.0.45:9100"


async def test_reconfigure_reports_an_unreachable_printer(hass, entry):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id}
    )
    with patch(
        "custom_components.epson_receipt_printer.config_flow._can_connect", return_value=False
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"host": "192.168.0.99", "port": 9100}
        )
    assert result["errors"] == {"base": "cannot_connect"}
    assert entry.data["host"] == "192.168.0.20"
