"""Small raw TCP ESC/POS client and receipt formatter."""

from __future__ import annotations

import io
import socket
from datetime import datetime

from PIL import Image, ImageOps


# ESC @ resets the printer; ESC t 19 selects code page PC858 (CP858), which
# has the euro sign and the accented letters CP437 lacks.
INIT = b"\x1b@\x1bt\x13"
# Typographic characters that phones and to-do apps insert, mapped to the
# closest printable form instead of "?".
_REPLACEMENTS = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'",
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u00ab": '"', "\u00bb": '"',
    "\u2013": "-", "\u2014": "-", "\u2212": "-", "\u2026": "...",
    "\u00a0": " ", "\u2009": " ", "\u202f": " ", "\u2022": "*",
})


def _text(value: str) -> bytes:
    safe = "".join(
        character
        for character in value.replace("\r", "").translate(_REPLACEMENTS)
        if character in "\n\t" or (ord(character) >= 0x20 and ord(character) != 0x7F)
    )
    return safe.encode("cp858", errors="replace")


def _ean13_check_digit(first_twelve: str) -> str:
    total = sum(int(digit) * (1 if index % 2 == 0 else 3) for index, digit in enumerate(first_twelve))
    return str((-total) % 10)


def _ean13(value: str, height: int) -> bytes:
    if not value.isascii() or not value.isdigit() or len(value) not in (12, 13):
        raise ValueError("EAN-13 data must contain 12 or 13 digits")
    digits = value[:12]
    check_digit = _ean13_check_digit(digits)
    if len(value) == 13 and value[-1] != check_digit:
        raise ValueError("The 13-digit EAN barcode has an invalid check digit")
    # Function A accepts the 12 data digits and a NUL terminator; the printer
    # calculates and prints the check digit itself.
    return b"\x1dh" + bytes((height,)) + b"\x1dH\x02\x1dk\x02" + digits.encode("ascii") + b"\x00"


def _code128(value: str, height: int) -> bytes:
    data = value.encode("ascii", errors="strict")
    if not data or any(byte < 0x20 or byte > 0x7E for byte in data):
        raise ValueError("Code 128 data must be printable ASCII")
    # Epson Code 128 requires the subset selector as the first two bytes.
    payload = b"{B" + data.replace(b"{", b"{{")
    if len(payload) > 255:
        raise ValueError("Code 128 data exceeds the printer's 255-byte limit")
    return b"\x1dh" + bytes((height,)) + b"\x1dH\x02\x1dkI" + bytes((len(payload),)) + payload


def _qr(value: str, module_size: int) -> bytes:
    payload = value.encode("utf-8")
    if not payload or len(payload) > 7089:
        raise ValueError("QR data must contain between 1 and 7,089 UTF-8 bytes")
    size = (len(payload) + 3).to_bytes(2, "little")
    return b"".join(
        (
            b"\x1d(k\x04\x001A2",
            b"\x1d(k\x03\x001C" + bytes((module_size,)),
            b"\x1d(k\x03\x001E1",
            b"\x1d(k" + size + b"1P0" + payload,
            b"\x1d(k\x03\x001Q0",
        )
    )


def _bonus_code(value: str, code_type: str, barcode_height: int, qr_size: int) -> bytes:
    if code_type == "auto":
        if value.startswith("_"):
            code_type, value = "qr", value[1:]
        elif value.isascii() and value.isdigit() and len(value) in (12, 13):
            code_type = "ean13"
        else:
            code_type = "code128"
    elif code_type == "qr" and value.startswith("_"):
        value = value[1:]

    if code_type == "qr":
        return _qr(value, qr_size)
    if code_type == "ean13":
        return _ean13(value, barcode_height)
    if code_type == "code128":
        return _code128(value, barcode_height)
    raise ValueError(f"Unsupported bonus code type: {code_type}")


def _style(size: str = "normal", bold: bool = False, underline: bool = False, font: str = "A") -> bytes:
    size_flag = {"normal": 0x00, "double_height": 0x10, "double_width": 0x20, "double": 0x30}[size]
    return (
        b"\x1bM" + (b"\x00" if font == "A" else b"\x01")
        + b"\x1bE" + (b"\x01" if bold else b"\x00")
        + b"\x1b-" + (b"\x01" if underline else b"\x00")
        + b"\x1d!" + bytes((size_flag,))
    )


def _alignment(value: str) -> bytes:
    return b"\x1ba" + {"left": b"\x00", "center": b"\x01", "right": b"\x02"}[value]


def _raster_image(
    image_data: bytes, max_width: int, alignment: str, printable_width_mm: float
) -> bytes:
    """Encode an image as an ESC/POS GS v 0 raster command."""
    with Image.open(io.BytesIO(image_data)) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGBA")
        background = Image.new("RGBA", image.size, "white")
        background.alpha_composite(image)
        image = ImageOps.contain(
            background.convert("RGB"), (max_width, 2048), Image.Resampling.LANCZOS
        )

    printable_width = round(printable_width_mm * 8)
    canvas = Image.new("RGB", (printable_width, image.height), "white")
    x = {
        "left": 0,
        "center": (printable_width - image.width) // 2,
        "right": printable_width - image.width,
    }[alignment]
    canvas.paste(image, (x, 0))
    image = canvas.convert("L").convert("1", dither=Image.Dither.FLOYDSTEINBERG)

    width, height = image.size
    row_bytes = (width + 7) // 8
    packed = bytearray(row_bytes * height)
    pixels = image.load()
    for y in range(height):
        row_offset = y * row_bytes
        for x in range(width):
            if pixels[x, y] == 0:
                packed[row_offset + x // 8] |= 0x80 >> (x % 8)

    return (
        b"\x1dv0\x00"
        + bytes((row_bytes & 0xFF, (row_bytes >> 8) & 0xFF, height & 0xFF, (height >> 8) & 0xFF))
        + bytes(packed)
        + b"\n"
    )


def _feed_dots(dots: int) -> bytes:
    """Feed an exact gap in printer dots (ESC J accepts at most 255 at once)."""
    output = bytearray()
    while dots:
        step = min(dots, 255)
        output.extend(b"\x1bJ" + bytes((step,)))
        dots -= step
    return bytes(output)


def build_blocks_receipt(
    blocks: list[dict], cut_paper: bool = True, printable_width_mm: float = 72
) -> bytes:
    """Compose styled text, raster images, and spacing in one receipt job."""
    if not blocks:
        raise ValueError("There are no content blocks to print")
    output = bytearray(INIT)
    for block in blocks:
        spacing_before = round(block.get("spacing_before_mm", 0) * 8)
        if spacing_before:
            output.extend(_feed_dots(spacing_before))
        kind = block["type"]
        if kind == "text":
            output.extend(_alignment(block["alignment"]))
            output.extend(
                _style(
                    block["text_size"],
                    bold=block["bold"],
                    underline=block["underline"],
                    font=block["font"],
                )
            )
            output.extend(_text(block["text"].rstrip("\n") + "\n"))
        elif kind == "image":
            output.extend(_alignment("left"))
            output.extend(_style())
            output.extend(
                _raster_image(
                    block["image_data"],
                    min(round(block["image_width_mm"] * 8), round(printable_width_mm * 8)),
                    block["alignment"],
                    printable_width_mm,
                )
            )
        elif kind == "qr":
            output.extend(_alignment(block["alignment"]))
            output.extend(_style())
            output.extend(_qr(block["data"], block["qr_size"]))
            output.extend(b"\n")
        elif kind == "barcode":
            output.extend(_alignment(block["alignment"]))
            output.extend(_style())
            if block["code_type"] == "ean13":
                output.extend(_ean13(block["data"], block["barcode_height"]))
            else:
                output.extend(_code128(block["data"], block["barcode_height"]))
            output.extend(b"\n")
        elif kind == "spacer":
            output.extend(_style())
            output.extend(_feed_dots(round(block["height_mm"] * 8)))
        else:
            raise ValueError(f"Unsupported Epson content block type: {kind}")
        spacing_after = round(block.get("spacing_after_mm", 0) * 8)
        if spacing_after:
            output.extend(_style())
            output.extend(_feed_dots(spacing_after))
    output.extend(_alignment("left"))
    output.extend(_style())
    output.extend(b"\x1bd\x02")
    if cut_paper:
        output.extend(b"\x1dVA\x32")
    return bytes(output)


def print_blocks(
    host: str,
    port: int,
    blocks: list[dict],
    cut_paper: bool = True,
    printable_width_mm: float = 72,
) -> None:
    send_raw(host, port, build_blocks_receipt(blocks, cut_paper, printable_width_mm))


def build_shopping_receipt(
    store: str,
    items: list[str],
    user: str = "",
    paid_back: str = "",
    bonus: str = "",
    title_alignment: str = "center",
    title_size: str = "normal",
    item_size: str = "normal",
    item_bold: bool = False,
    item_prefix: str = "checkbox",
    show_timestamp: bool = True,
    thank_you: str = "auto",
    bonus_type: str = "auto",
    barcode_height: int = 100,
    qr_size: int = 6,
    cut_paper: bool = True,
    timestamp: str | None = None,
) -> bytes:
    has_bonus = bool(bonus.strip()) and bonus.strip().lower() != "none"
    if not items and not has_bonus:
        raise ValueError("There are no active items to print")

    timestamp = timestamp or datetime.now().astimezone().strftime("%d/%m/%Y %H:%M")
    output = bytearray(INIT)
    output.extend(_alignment(title_alignment))
    output.extend(_style(title_size, bold=True))
    output.extend(_text(f"{store or 'Shopping'} list\n"))
    output.extend(_alignment("left"))
    output.extend(_style())
    output.extend(_text("=" * 24 + "\n"))

    output.extend(_style(item_size, bold=item_bold))
    for index, item in enumerate(items, start=1):
        prefix = {
            "checkbox": "[ ] ",
            "bullet": "* ",
            "dash": "- ",
            "none": "",
            "number": f"{index}. ",
        }[item_prefix]
        output.extend(_text(f"{prefix}{item}\n"))

    output.extend(_style())
    output.extend(_text("=" * 24 + "\n"))

    if has_bonus:
        output.extend(_alignment("center"))
        output.extend(_style(bold=True))
        output.extend(_text("Loyalty card\n"))
        output.extend(_style())
        output.extend(_bonus_code(bonus, bonus_type, barcode_height, qr_size))
        output.extend(b"\n\n")
        output.extend(_alignment("left"))

    should_thank = thank_you == "always" or (thank_you == "auto" and bool(paid_back.strip()))
    if should_thank:
        output.extend(_alignment("center"))
        output.extend(_style("double_width", bold=True))
        output.extend(_text(f"Thanks for shopping,\n{user}! <3\n" if user else "Thanks for shopping!\n"))
        output.extend(_style())
        output.extend(b"\n")
        output.extend(_alignment("left"))

    if paid_back.strip():
        output.extend(_alignment("center"))
        output.extend(b"\x1bM\x01\x1b-\x01")
        output.extend(_text("Paid back checklist:\n"))
        output.extend(b"\x1b-\x00\x1bM\x00")
        output.extend(_text(paid_back.strip() + "\n\n"))

    output.extend(_alignment("left"))
    output.extend(_text("-" * 24 + "\n"))
    if show_timestamp:
        output.extend(_text(f"(Finalized at {timestamp})\n\n"))
    else:
        output.extend(_text("\n"))
    output.extend(b"\x1bd\x02")
    if cut_paper:
        output.extend(b"\x1dVA\x32")
    return bytes(output)


def send_raw(host: str, port: int, data: bytes, timeout: float = 5.0) -> None:
    """Send one complete print job over one TCP connection."""
    with socket.create_connection((host, port), timeout=timeout) as printer:
        printer.sendall(data)


def print_shopping_receipt(
    host: str,
    port: int,
    store: str,
    items: list[str],
    user: str = "",
    paid_back: str = "",
    bonus: str = "",
    title_alignment: str = "center",
    title_size: str = "normal",
    item_size: str = "normal",
    item_bold: bool = False,
    item_prefix: str = "checkbox",
    show_timestamp: bool = True,
    thank_you: str = "auto",
    bonus_type: str = "auto",
    barcode_height: int = 100,
    qr_size: int = 6,
    cut_paper: bool = True,
    timestamp: str | None = None,
) -> None:
    send_raw(
        host,
        port,
        build_shopping_receipt(
            store,
            items,
            user,
            paid_back,
            bonus,
            title_alignment,
            title_size,
            item_size,
            item_bold,
            item_prefix,
            show_timestamp,
            thank_you,
            bonus_type,
            barcode_height,
            qr_size,
            cut_paper,
            timestamp,
        ),
    )


def print_text(
    host: str,
    port: int,
    text: str,
    alignment: str = "left",
    size: str = "normal",
    font: str = "A",
    bold: bool = False,
    underline: bool = False,
    cut_paper: bool = True,
) -> None:
    payload = bytearray(INIT)
    payload.extend(_alignment(alignment))
    payload.extend(_style(size, bold=bold, underline=underline, font=font))
    payload.extend(_text(text.strip() + "\n\n"))
    payload.extend(_style())
    payload.extend(b"\x1bd\x02")
    if cut_paper:
        payload.extend(b"\x1dVA\x32")
    send_raw(host, port, bytes(payload))
