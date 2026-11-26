"""The printer device shows whether the printer is reachable."""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import patch

from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.epson_receipt_printer.const import DOMAIN

CAN_CONNECT = "custom_components.epson_receipt_printer.binary_sensor._can_connect"


async def test_online_follows_the_printer(hass):
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="192.168.0.40:9100", title="Printer",
        data={"name": "Printer", "host": "192.168.0.40", "port": 9100,
              "printer_model": "QL-710W", "label_size": "62", "tape_width_mm": "12"},
    )
    entry.add_to_hass(hass)
    with patch(CAN_CONNECT, return_value=True):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    entity_id = next(s.entity_id for s in hass.states.async_all("binary_sensor"))
    assert hass.states.get(entity_id).state == "on"
    assert hass.states.get(entity_id).attributes["device_class"] == "connectivity"

    with patch(CAN_CONNECT, return_value=False):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(minutes=2))
        await hass.async_block_till_done()
    assert hass.states.get(entity_id).state == "off"

    assert await hass.config_entries.async_unload(entry.entry_id)
