"""Minimal library example: discover one bulb and run a small light sequence."""

from __future__ import annotations

import time

from yeelight_re import YeelightClient, discover

YELLOW = 0xFFC24D
BLUE = 0x3B82F6


def main() -> int:
    devices = discover(timeout=2.0)
    if not devices:
        print("No bulb found. Enable LAN Control and try again.")
        return 1
    device = devices[0]
    print(f"Using {device.name or device.model} at {device.ip}:{device.port}")

    with YeelightClient(device.ip, device.port, timeout=5.0) as bulb:
        print("Before:", bulb.status())
        bulb.set_power(True, "smooth", 300)
        bulb.set_bright(35, "smooth", 300)
        bulb.set_rgb(YELLOW, "smooth", 400)
        time.sleep(1.0)
        bulb.set_rgb(BLUE, "smooth", 400)
        time.sleep(1.0)
        bulb.set_ct(3000, "smooth", 500)
        print("After :", bulb.status())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
