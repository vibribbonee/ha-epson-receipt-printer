"""A printer that gets a new IP is moved, not offered as a new device."""
from __future__ import annotations

from ipaddress import ip_address

from homeassistant import config_entries
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.epson_receipt_printer.const import DOMAIN

NAME = "Kitchen printer._pdl-datastream._tcp.local."


def _discovery(host: str, name: str = NAME) -> ZeroconfServiceInfo:
    return ZeroconfServiceInfo(
        ip_address=ip_address(host), ip_addresses=[ip_address(host)], port=9100,
        hostname="printer.local.", type="_pdl-datastream._tcp.local.", name=name,
        properties={"ty": "Brother TM-T70II" if "epson_receipt_printer".startswith("brother") else "EPSON TM-T70II"},
    )


async def _discover(hass, host, name=NAME):
    return await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_ZEROCONF}, data=_discovery(host, name)
    )


async def _entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id="192.168.0.40:9100", title="Printer",
        data={"name": "Printer", "host": "192.168.0.40", "port": 9100,
              "printer_model": "TM-T70II", "label_size": "62", "tape_width_mm": "12"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_learns_the_name_then_follows_a_new_address(hass):
    entry = await _entry(hass)
    result = await _discover(hass, "192.168.0.40")
    assert result["reason"] == "already_configured"
    assert entry.data["zeroconf_name"] == NAME

    result = await _discover(hass, "192.168.0.57")
    await hass.async_block_till_done()
    assert result["reason"] == "already_configured"
    assert entry.data["host"] == "192.168.0.57"
    assert entry.unique_id == "192.168.0.57:9100"
    assert not hass.config_entries.flow.async_progress()


async def test_an_unknown_printer_is_still_offered(hass):
    await _entry(hass)
    result = await _discover(hass, "192.168.0.99", name="Other._pdl-datastream._tcp.local.")
    assert result["step_id"] == "confirm"
