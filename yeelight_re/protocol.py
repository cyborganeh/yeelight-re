"""Wire protocol helpers for the Yeelight LAN API.

The protocol is intentionally simple:

* SSDP-like discovery on UDP 1982 (multicast 239.255.255.250).
* Newline-delimited JSON over TCP 55443.

Nothing in this module opens a socket; it only parses/builds messages so it can
be unit-tested and reused by the client, the CLI and the fake bulb.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

SSDP_ADDRESS = "239.255.255.250"
SSDP_PORT = 1982
CONTROL_PORT = 55443
DEFAULT_TIMEOUT = 5.0

M_SEARCH = (
    "M-SEARCH * HTTP/1.1\r\n"
    f"HOST: {SSDP_ADDRESS}:{SSDP_PORT}\r\n"
    'MAN: "ssdp:discover"\r\n'
    "ST: wifi_bulb\r\n"
    "\r\n"
).encode("ascii")

#: Properties that are useful for a status screen and are supported by the
#: vast majority of Yeelight devices. Unknown properties are returned as "".
STATUS_PROPS = (
    "power",
    "bright",
    "ct",
    "rgb",
    "hue",
    "sat",
    "color_mode",
    "flowing",
    "delayoff",
    "music_on",
    "name",
)

#: Properties whose values are integers (when present).
INT_PROPS = {
    "bright",
    "ct",
    "rgb",
    "hue",
    "sat",
    "color_mode",
    "flowing",
    "delayoff",
    "music_on",
}

COLOR_MODES = {
    0: "normal",
    1: "color-temperature",
    2: "rgb",
    3: "hsv",
}

EFFECTS = ("smooth", "sudden")
FLOW_ACTIONS = {
    0: "recover",
    1: "stay",
    2: "turn-off",
}

ERROR_CODES = {
    -1: "general error",
    -2: "client quota exceeded",
    -3: "invalid params",
    -4: "method not supported",
    -5: "device is offline / internal error",
}


class YeelightError(Exception):
    """Base class for all errors raised by this package."""


class ProtocolError(YeelightError):
    """A malformed or unexpected protocol message was received."""


class YeelightTimeout(YeelightError):
    """The bulb did not answer before the deadline."""


class LanControlDisabled(YeelightError):
    """TCP 55443 refused the connection (LAN Control is probably off)."""


class CommandError(YeelightError):
    """The bulb answered with a JSON ``error`` object."""

    def __init__(self, code: int, message: str, method: str | None = None):
        self.code = int(code)
        self.message = message
        self.method = method
        detail = f"error {self.code}: {message}"
        if method:
            detail = f"{method}: {detail}"
        super().__init__(detail)


def describe_error(code: int) -> str:
    """Return the documented meaning of a Yeelight error code (best effort)."""
    return ERROR_CODES.get(int(code), "unknown error")


@dataclass(frozen=True)
class Device:
    """A device as described by an SSDP discovery response."""

    ip: str
    port: int = CONTROL_PORT
    id: str = ""
    model: str = ""
    fw_ver: str = ""
    support: tuple[str, ...] = ()
    power: str = ""
    bright: int | None = None
    color_mode: int | None = None
    ct: int | None = None
    rgb: int | None = None
    hue: int | None = None
    sat: int | None = None
    name: str = ""
    raw: Mapping[str, str] = field(default_factory=dict, compare=False, repr=False)

    @property
    def location(self) -> str:
        return f"yeelight://{self.ip}:{self.port}"

    @property
    def is_color(self) -> bool:
        return self.model.startswith("color") or "set_rgb" in self.support

    def as_dict(self) -> dict[str, Any]:
        return {
            "ip": self.ip,
            "port": self.port,
            "id": self.id,
            "model": self.model,
            "fw_ver": self.fw_ver,
            "support": list(self.support),
            "power": self.power,
            "bright": self.bright,
            "color_mode": self.color_mode,
            "ct": self.ct,
            "rgb": self.rgb,
            "hue": self.hue,
            "sat": self.sat,
            "name": self.name,
        }


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_ssdp(payload: bytes | str, address: tuple[str, int] | None = None) -> Device | None:
    """Parse one SSDP response.

    ``address`` is the UDP source address, used only as a fallback when the
    ``Location`` header is missing.
    """
    if isinstance(payload, bytes):
        text = payload.decode("utf-8", "replace")
    else:
        text = payload
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines:
        return None
    status = lines[0].strip()
    if status and "200" not in status:
        return None

    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()

    location = headers.get("location", "")
    ip = ""
    port = CONTROL_PORT
    match = re.search(r"yeelight://\[?([^\]/:]+)\]?(?::(\d+))?", location)
    if match:
        ip = match.group(1)
        if match.group(2):
            port = int(match.group(2))
    elif address:
        ip = address[0]
    if not ip:
        return None

    return Device(
        ip=ip,
        port=port,
        id=headers.get("id", ""),
        model=headers.get("model", ""),
        fw_ver=headers.get("fw_ver", ""),
        support=tuple(headers.get("support", "").split()),
        power=headers.get("power", ""),
        bright=_as_int(headers.get("bright")),
        color_mode=_as_int(headers.get("color_mode")),
        ct=_as_int(headers.get("ct")),
        rgb=_as_int(headers.get("rgb")),
        hue=_as_int(headers.get("hue")),
        sat=_as_int(headers.get("sat")),
        name=headers.get("name", ""),
        raw=headers,
    )


def format_command(message_id: int, method: str, params: Sequence[Any] | None = None) -> bytes:
    """Serialize one command, terminated with CRLF as required by the bulb."""
    message = {
        "id": int(message_id),
        "method": str(method),
        "params": list(params or []),
    }
    return json.dumps(message, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\r\n"


def parse_message(line: bytes | str) -> dict[str, Any]:
    """Parse a single JSON line and require a JSON object."""
    if isinstance(line, bytes):
        text = line.decode("utf-8", "replace")
    else:
        text = line
    text = text.strip()
    if not text:
        raise ProtocolError("empty message")
    try:
        message = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProtocolError(f"invalid JSON: {text[:120]!r}") from exc
    if not isinstance(message, dict):
        raise ProtocolError("message is not a JSON object")
    return message


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def parse_rgb(value: str | int) -> int:
    """Accept ``0xRRGGBB``, ``#RRGGBB``, ``RRGGBB``, ``r,g,b`` or an integer."""
    if isinstance(value, int):
        rgb = value
    else:
        text = value.strip().lower()
        force_hex = False
        if text.startswith("#"):
            text = text[1:]
            force_hex = True
        if text.startswith("0x"):
            text = text[2:]
            force_hex = True
        if not text:
            raise ValueError("empty RGB value")
        if "," in text:
            parts = [part.strip() for part in text.split(",")]
            if len(parts) != 3:
                raise ValueError("RGB must be 'r,g,b' with three components")
            red, green, blue = (int(part, 10) for part in parts)
            if not all(0 <= component <= 255 for component in (red, green, blue)):
                raise ValueError("RGB components must be between 0 and 255")
            rgb = (red << 16) | (green << 8) | blue
        else:
            rgb = int(text, 16 if force_hex or not text.isdigit() else 10)
    if not 0 <= rgb <= 0xFFFFFF:
        raise ValueError("RGB must be between 0x000000 and 0xFFFFFF")
    return rgb


def rgb_to_hex(rgb: int) -> str:
    return f"#{int(rgb) & 0xFFFFFF:06x}"


def rgb_components(rgb: int) -> tuple[int, int, int]:
    value = int(rgb) & 0xFFFFFF
    return (value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF


def rgb_from_hsv(hue: int, sat: int) -> int:
    """Convert Yeelight HSV (hue 0-359, sat/val 0-100) to a 24-bit RGB value."""
    hue = clamp(hue, 0, 359)
    sat = clamp(sat, 0, 100) / 100.0
    value = 1.0
    sector = (hue % 360) / 60.0
    chroma = value * sat
    x = chroma * (1 - abs(sector % 2 - 1))
    m = value - chroma
    if sector < 1:
        red, green, blue = chroma, x, 0
    elif sector < 2:
        red, green, blue = x, chroma, 0
    elif sector < 3:
        red, green, blue = 0, chroma, x
    elif sector < 4:
        red, green, blue = 0, x, chroma
    elif sector < 5:
        red, green, blue = x, 0, chroma
    else:
        red, green, blue = chroma, 0, x
    return (
        (round((red + m) * 255) << 16)
        | (round((green + m) * 255) << 8)
        | round((blue + m) * 255)
    )


def build_flow(steps: Iterable[Sequence[int]]) -> str:
    """Build a flow expression from ``(duration_ms, mode, value, brightness)`` rows.

    mode 1 = RGB (value is 24-bit RGB), mode 2 = color temperature (Kelvin),
    mode 7 = sleep (value ignored). Durations are milliseconds, minimum 50.
    """
    chunks: list[str] = []
    for index, step in enumerate(steps, start=1):
        if len(step) != 4:
            raise ValueError(f"flow step {index} must have four values")
        duration, mode, value, brightness = (int(item) for item in step)
        if duration < 50:
            raise ValueError(f"flow step {index}: duration must be >= 50 ms")
        if mode not in (1, 2, 7):
            raise ValueError(f"flow step {index}: unsupported mode {mode}")
        if mode in (1, 2) and not 1 <= brightness <= 100:
            raise ValueError(f"flow step {index}: brightness must be 1-100")
        if mode == 1 and not 0 <= value <= 0xFFFFFF:
            raise ValueError(f"flow step {index}: RGB out of range")
        if mode == 2 and not 1700 <= value <= 6500:
            raise ValueError(f"flow step {index}: color temperature must be 1700-6500 K")
        chunks.extend((str(duration), str(mode), str(value), str(brightness)))
    if not chunks:
        raise ValueError("a flow needs at least one step")
    return ",".join(chunks)
