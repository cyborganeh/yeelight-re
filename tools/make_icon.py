"""Generate the Windows icon used for the executable.

Pure standard library: the PNG frames are built by hand and packed into an
ICO container. Run with ``python tools/make_icon.py``.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

OUTPUT = Path(__file__).resolve().parent.parent / "packaging" / "yeelight.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)
SUPERSAMPLE = 3


def _chunk(tag: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", checksum)


def _colour(x: float, y: float) -> tuple[int, int, int, int]:
    # Soft glow around the glass.
    distance = ((x - 0.5) ** 2 + (y - 0.38) ** 2) ** 0.5
    if 0.25 < distance <= 0.32:
        return (255, 170, 40, 55)

    # Glass.
    if distance <= 0.25:
        shade = int(255 - 40 * max(0.0, (y - 0.26) / 0.37))
        if (x - 0.415) ** 2 + (y - 0.30) ** 2 <= 0.05 ** 2:
            return (255, 255, 255, 190)
        return (255, shade, 64, 255)

    # Neck between glass and base.
    if 0.60 <= y <= 0.665:
        progress = (y - 0.60) / 0.065
        half_width = 0.10 - 0.015 * progress
        if abs(x - 0.5) <= half_width:
            return (176, 184, 194, 255)

    # Screw base with a rounded bottom.
    if 0.65 <= y <= 0.80:
        half_width = 0.115
        radius = 0.025
        dx = abs(x - 0.5)
        if y > 0.80 - radius and dx > half_width - radius:
            if (dx - (half_width - radius)) ** 2 + (y - (0.80 - radius)) ** 2 > radius ** 2:
                return (0, 0, 0, 0)
        if dx <= half_width:
            if 0.675 <= y <= 0.692 or 0.717 <= y <= 0.734 or 0.759 <= y <= 0.776:
                return (108, 117, 128, 255)
            return (154, 165, 177, 255)

    return (0, 0, 0, 0)


def _render(size: int) -> bytes:
    rows = []
    step = 1.0 / (size * SUPERSAMPLE)
    for py in range(size):
        row = bytearray([0])
        for px in range(size):
            red = green = blue = alpha = 0
            for sy in range(SUPERSAMPLE):
                for sx in range(SUPERSAMPLE):
                    x = (px * SUPERSAMPLE + sx + 0.5) * step
                    y = (py * SUPERSAMPLE + sy + 0.5) * step
                    r, g, b, a = _colour(x, y)
                    red += r * a
                    green += g * a
                    blue += b * a
                    alpha += a
            samples = SUPERSAMPLE * SUPERSAMPLE
            if alpha:
                row += bytes((red // alpha, green // alpha, blue // alpha, alpha // samples))
            else:
                row += bytes((0, 0, 0, 0))
        rows.append(bytes(row))
    raw = b"".join(rows)
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


def main() -> int:
    frames = [(size, _render(size)) for size in SIZES]
    offset = 6 + 16 * len(frames)
    entries = b""
    payload = b""
    for size, png in frames:
        entries += struct.pack(
            "<BBBBHHII",
            size if size < 256 else 0,
            size if size < 256 else 0,
            0,
            0,
            1,
            32,
            len(png),
            offset,
        )
        offset += len(png)
        payload += png
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_bytes(struct.pack("<HHH", 0, 1, len(frames)) + entries + payload)
    preview = OUTPUT.with_name("yeelight-preview.png")
    preview.write_bytes(dict(frames)[256])
    print(f"Wrote {OUTPUT} ({OUTPUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
