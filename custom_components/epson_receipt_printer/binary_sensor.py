"""Show whether the printer answers on its raw print port."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
)

from .config_flow import _can_connect
from .const import DOMAIN

# Often enough to catch a printer that was switched off, rare enough not to
# disturb a printer that accepts one connection at a time.
CHECK_INTERVAL = timedelta(minutes=1)
_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async def check() -> bool:
        return await _can_connect(entry.data[CONF_HOST], int(entry.data[CONF_PORT]))

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        config_entry=entry,
        name=f"{DOMAIN} {entry.title}",
        update_method=check,
        update_interval=CHECK_INTERVAL,
    )
    await coordinator.async_refresh()
    async_add_entities([PrinterOnline(coordinator, entry)])


class PrinterOnline(CoordinatorEntity[DataUpdateCoordinator[bool]], BinarySensorEntity):
    """On while the printer accepts connections on its print port."""

    _attr_has_entity_name = True
    _attr_name = "Online"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: DataUpdateCoordinator[bool], entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_online"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Epson",
            model="ESC/POS receipt printer",
            configuration_url=f"http://{entry.data[CONF_HOST]}",
        )

    @property
    def available(self) -> bool:
        # The check itself never fails; "off" already means unreachable.
        return True

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data)
