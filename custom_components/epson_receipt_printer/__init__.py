"""Home Assistant actions for network ESC/POS receipt printers."""

from __future__ import annotations

import asyncio
from pathlib import Path

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import ATTR_CONFIG_ENTRY_ID, Platform, CONF_ENTITY_ID
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv, service
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .const import CONF_HOST, CONF_PORT, DOMAIN, SERVICE_PRINT_SHOPPING_LIST, SERVICE_PRINT_TEXT
from .escpos import print_blocks, print_shopping_receipt, print_text

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
PLATFORMS = [Platform.BINARY_SENSOR]
BLOCK_SCHEMA = vol.Schema(
    {
        vol.Required("type"): vol.In(("text", "image", "spacer", "todo_list", "qr", "barcode")),
        vol.Optional("text"): cv.string,
        vol.Optional("image_path"): cv.string,
        vol.Optional("entity_id"): cv.entity_id,
        vol.Optional("data"): cv.string,
        vol.Optional("item_prefix", default="checkbox"): vol.In(("checkbox", "bullet", "dash", "none", "number")),
        vol.Optional("alignment", default="left"): vol.In(("left", "center", "right")),
        vol.Optional("text_size", default="normal"): vol.In(("normal", "double_height", "double_width", "double")),
        vol.Optional("font", default="A"): vol.In(("A", "B")),
        vol.Optional("bold", default=False): cv.boolean,
        vol.Optional("underline", default=False): cv.boolean,
        vol.Optional("image_width_mm", default=72): vol.All(vol.Coerce(float), vol.Range(min=1, max=72)),
        vol.Optional("spacing_before_mm", default=0): vol.All(vol.Coerce(float), vol.Range(min=0, max=25)),
        vol.Optional("spacing_after_mm", default=0): vol.All(vol.Coerce(float), vol.Range(min=0, max=25)),
        vol.Optional("height_mm", default=3): vol.All(vol.Coerce(float), vol.Range(min=1, max=100)),
        vol.Optional("qr_size", default=6): vol.All(cv.positive_int, vol.Range(min=1, max=16)),
        vol.Optional("code_type", default="code128"): vol.In(("ean13", "code128")),
        vol.Optional("barcode_height", default=100): vol.All(cv.positive_int, vol.Range(min=20, max=255)),
    },
    extra=vol.PREVENT_EXTRA,
)

PRINT_TEXT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Optional("text"): cv.string,
        vol.Optional("blocks"): [BLOCK_SCHEMA],
        vol.Optional("alignment", default="left"): vol.In(("left", "center", "right")),
        vol.Optional("text_size", default="normal"): vol.In(("normal", "double_height", "double_width", "double")),
        vol.Optional("font", default="A"): vol.In(("A", "B")),
        vol.Optional("bold", default=False): cv.boolean,
        vol.Optional("underline", default=False): cv.boolean,
        vol.Optional("printable_width_mm", default=72): vol.All(vol.Coerce(int), vol.In((52, 72))),
        vol.Optional("cut_paper", default=True): cv.boolean,
    }
)
PRINT_SHOPPING_LIST_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY_ID): cv.string,
        vol.Required(CONF_ENTITY_ID): cv.entity_id,
        vol.Optional("store", default="Shopping"): cv.string,
        vol.Optional("user", default=""): cv.string,
        vol.Optional("paid_back", default=""): cv.string,
        vol.Optional("bonus", default=""): cv.string,
        vol.Optional("title_alignment", default="center"): vol.In(("left", "center", "right")),
        vol.Optional("title_size", default="normal"): vol.In(("normal", "double_height", "double_width", "double")),
        vol.Optional("item_size", default="normal"): vol.In(("normal", "double_height", "double_width", "double")),
        vol.Optional("item_bold", default=False): cv.boolean,
        vol.Optional("item_prefix", default="checkbox"): vol.In(("checkbox", "bullet", "dash", "none", "number")),
        vol.Optional("show_timestamp", default=True): cv.boolean,
        vol.Optional("thank_you", default="auto"): vol.In(("auto", "always", "never")),
        vol.Optional("bonus_type", default="auto"): vol.In(("auto", "qr", "ean13", "code128")),
        vol.Optional("barcode_height", default=100): vol.All(cv.positive_int, vol.Range(min=20, max=255)),
        vol.Optional("qr_size", default=6): vol.All(cv.positive_int, vol.Range(min=1, max=16)),
        vol.Optional("cut_paper", default=True): cv.boolean,
    }
)


def _read_image(hass: HomeAssistant, relative_path: str) -> bytes:
    """Read images only from /config/www."""
    root = Path(hass.config.path("www")).resolve()
    requested = Path(relative_path)
    if requested.is_absolute():
        raise ValueError("image_path must be relative to /config/www")
    image_path = (root / requested).resolve()
    if image_path != root and root not in image_path.parents:
        raise ValueError("image_path must stay inside /config/www")
    return image_path.read_bytes()


async def _async_todo_items(hass: HomeAssistant, list_entity: str) -> list[str]:
    """Return the active item names of a to-do list."""
    response = await hass.services.async_call(
        "todo",
        "get_items",
        {CONF_ENTITY_ID: list_entity, "status": "needs_action"},
        blocking=True,
        return_response=True,
    )
    return [
        str(item.get("summary", "")).strip()
        for item in response.get(list_entity, {}).get("items", [])
        if str(item.get("summary", "")).strip()
    ]


def _get_printer_entry(
    hass: HomeAssistant, entry_id: str
) -> config_entries.ConfigEntry:
    """Resolve a loaded printer entry across Home Assistant versions."""
    get_entry = getattr(service, "async_get_config_entry", None)
    if get_entry is not None:
        return get_entry(hass, DOMAIN, entry_id)

    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise ServiceValidationError("The selected Epson printer entry was not found.")
    if entry.state is not config_entries.ConfigEntryState.LOADED:
        raise ServiceValidationError(
            f"The selected Epson printer {entry.title} is not loaded."
        )
    return entry


def _get_print_lock(hass: HomeAssistant, entry_id: str) -> asyncio.Lock:
    """Serialize jobs sent to the same printer."""
    locks = hass.data.setdefault(DOMAIN, {}).setdefault("print_locks", {})
    if entry_id not in locks:
        locks[entry_id] = asyncio.Lock()
    return locks[entry_id]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register actions whether or not a printer entry is loaded yet."""

    async def async_print_text(call: ServiceCall) -> None:
        entry = _get_printer_entry(hass, call.data[ATTR_CONFIG_ENTRY_ID])
        try:
            blocks = call.data.get("blocks")
            text = call.data.get("text", "")
            if bool(text.strip()) == (blocks is not None):
                raise ServiceValidationError("Provide either text or blocks, but not both.")
            if blocks is not None:
                if not blocks:
                    raise ServiceValidationError("Provide at least one Epson content block.")
                prepared_blocks = []
                for index, source in enumerate(blocks, start=1):
                    block = dict(source)
                    if block["type"] == "text":
                        if not block.get("text", "").strip():
                            raise ServiceValidationError(f"Epson text block {index} needs non-empty text.")
                        block["text"] = block["text"].strip()
                    elif block["type"] == "image":
                        image_path = block.get("image_path", "").strip()
                        if not image_path:
                            raise ServiceValidationError(f"Epson image block {index} needs image_path.")
                        try:
                            block["image_data"] = await hass.async_add_executor_job(
                                _read_image, hass, image_path
                            )
                        except (OSError, ValueError) as err:
                            raise ServiceValidationError(
                                f"Epson image block {index} could not read {image_path}: {err}"
                            ) from err
                    elif block["type"] == "todo_list":
                        list_entity = block.get("entity_id", "")
                        if not list_entity:
                            raise ServiceValidationError(
                                f"Epson to-do block {index} needs entity_id."
                            )
                        items = await _async_todo_items(hass, list_entity)
                        prefixes = {
                            "checkbox": "[ ] ",
                            "bullet": "* ",
                            "dash": "- ",
                            "none": "",
                            "number": None,
                        }
                        prefix = prefixes[block["item_prefix"]]
                        lines = [
                            f"{number}. {item}" if prefix is None else f"{prefix}{item}"
                            for number, item in enumerate(items, start=1)
                        ]
                        block["type"] = "text"
                        block["text"] = "\n".join(lines) if lines else "No active items"
                    elif block["type"] in ("qr", "barcode"):
                        if not block.get("data", "").strip():
                            raise ServiceValidationError(
                                f"Epson {block['type']} block {index} needs data."
                            )
                    prepared_blocks.append(block)
                async with _get_print_lock(hass, entry.entry_id):
                    await hass.async_add_executor_job(
                        print_blocks,
                        entry.data[CONF_HOST],
                        entry.data[CONF_PORT],
                        prepared_blocks,
                        call.data["cut_paper"],
                        call.data["printable_width_mm"],
                    )
            else:
                async with _get_print_lock(hass, entry.entry_id):
                    await hass.async_add_executor_job(
                        print_text,
                        entry.data[CONF_HOST],
                        entry.data[CONF_PORT],
                        text,
                        call.data["alignment"],
                        call.data["text_size"],
                        call.data["font"],
                        call.data["bold"],
                        call.data["underline"],
                        call.data["cut_paper"],
                    )
        except ServiceValidationError:
            raise
        except Exception as err:
            raise HomeAssistantError(f"Could not print to {entry.title}: {err}") from err

    async def async_print_shopping_list(call: ServiceCall) -> None:
        entry = _get_printer_entry(hass, call.data[ATTR_CONFIG_ENTRY_ID])
        list_entity = call.data[CONF_ENTITY_ID]
        try:
            items = await _async_todo_items(hass, list_entity)
            async with _get_print_lock(hass, entry.entry_id):
                await hass.async_add_executor_job(
                    print_shopping_receipt,
                    entry.data[CONF_HOST],
                    entry.data[CONF_PORT],
                    call.data["store"],
                    items,
                    call.data["user"],
                    call.data["paid_back"],
                    call.data["bonus"],
                    call.data["title_alignment"],
                    call.data["title_size"],
                    call.data["item_size"],
                    call.data["item_bold"],
                    call.data["item_prefix"],
                    call.data["show_timestamp"],
                    call.data["thank_you"],
                    call.data["bonus_type"],
                    call.data["barcode_height"],
                    call.data["qr_size"],
                    call.data["cut_paper"],
                    dt_util.now().strftime("%d/%m/%Y %H:%M"),
                )
        except ServiceValidationError:
            raise
        except Exception as err:
            raise HomeAssistantError(f"Could not print the shopping list to {entry.title}: {err}") from err

    hass.services.async_register(
        DOMAIN,
        SERVICE_PRINT_TEXT,
        async_print_text,
        schema=PRINT_TEXT_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_PRINT_SHOPPING_LIST,
        async_print_shopping_list,
        schema=PRINT_SHOPPING_LIST_SCHEMA,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: config_entries.ConfigEntry) -> bool:
    """A config entry represents one network printer."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: config_entries.ConfigEntry) -> bool:
    """Unload one printer entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
