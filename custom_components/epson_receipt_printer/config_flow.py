"""Config flow for network ESC/POS printers."""

from __future__ import annotations

import asyncio

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PORT
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
)

try:
    from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo
except ImportError:  # Home Assistant before the 2026.1 service-info move.
    from homeassistant.components.zeroconf import ZeroconfServiceInfo

from .const import DEFAULT_PORT, DOMAIN


async def _can_connect(host: str, port: int) -> bool:
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=3
        )
        writer.close()
        await writer.wait_closed()
        return True
    except (OSError, asyncio.TimeoutError):
        return False


class EpsonReceiptPrinterConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Add an Epson or other ESC/POS printer reachable over TCP."""

    VERSION = 1

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ):
        """Offer to configure a TM-T70II when its raw print service is advertised."""
        details = " ".join(
            [
                discovery_info.name,
                *(
                    f"{key} {value.decode(errors='ignore') if isinstance(value, bytes) else value}"
                    for key, value in discovery_info.properties.items()
                ),
            ]
        ).lower()
        if "tm-t70ii" not in details and "tm-t70ii" not in discovery_info.name.lower():
            return self.async_abort(reason="unsupported_device")

        host = str(discovery_info.host)
        port = discovery_info.port
        await self.async_set_unique_id(f"{host.lower()}:{port}")
        self._abort_if_unique_id_configured()
        name = f"Epson TM-T70II at {host}"
        self.context["title_placeholders"] = {"name": name}
        self._discovered_data = {
            CONF_NAME: name,
            CONF_HOST: host,
            CONF_PORT: port,
        }
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input=None):
        """Confirm adding the discovered printer."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovered_data[CONF_NAME], data=self._discovered_data
            )
        self._set_confirm_only()
        return self.async_show_form(step_id="confirm")

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input[CONF_PORT])
            if not await _can_connect(host, port):
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(f"{host.lower()}:{port}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_NAME].strip() or f"Epson at {host}",
                    data={CONF_NAME: user_input[CONF_NAME].strip(), CONF_HOST: host, CONF_PORT: port},
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default="Epson TM-T70II"): TextSelector(),
                vol.Required(CONF_HOST): TextSelector(),
                vol.Required(CONF_PORT, default=DEFAULT_PORT): NumberSelector(
                    NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX)
                ),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_reconfigure(self, user_input=None):
        """Point an existing printer at a new address, e.g. after a DHCP change."""
        entry = self._get_reconfigure_entry()
        errors = {}
        if user_input is not None:
            host = user_input[CONF_HOST].strip()
            port = int(user_input[CONF_PORT])
            if not await _can_connect(host, port):
                errors["base"] = "cannot_connect"
            else:
                unique_id = f"{host.lower()}:{port}"
                if any(
                    other.unique_id == unique_id and other.entry_id != entry.entry_id
                    for other in self._async_current_entries()
                ):
                    return self.async_abort(reason="already_configured")
                return self.async_update_reload_and_abort(
                    entry,
                    unique_id=unique_id,
                    data_updates={CONF_HOST: host, CONF_PORT: port},
                )
        schema = vol.Schema(
            {
                vol.Required(CONF_HOST, default=entry.data[CONF_HOST]): TextSelector(),
                vol.Required(CONF_PORT, default=entry.data[CONF_PORT]): NumberSelector(
                    NumberSelectorConfig(min=1, max=65535, mode=NumberSelectorMode.BOX)
                ),
            }
        )
        return self.async_show_form(step_id="reconfigure", data_schema=schema, errors=errors)
