"""Capture a bulb's discovery data and current state into JSON.

Usage (from the project root):

    python tools/capture.py --ip 192.168.1.20
    python tools/capture.py --ip 192.168.1.20 -o captures/kamar.json

This is not a packet capture. Use Wireshark/tshark with
``tcp.port == 55443 || udp.port == 1982`` for raw traffic.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from yeelight_re.client import YeelightClient  # noqa: E402
from yeelight_re.discovery import discover, local_ipv4, unique_by_ip  # noqa: E402
from yeelight_re.protocol import CONTROL_PORT, YeelightError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Capture Yeelight discovery + state")
    parser.add_argument("--ip", help="target bulb (default: auto-discover one bulb)")
    parser.add_argument("--port", type=int, default=CONTROL_PORT)
    parser.add_argument("--timeout", type=float, default=3.0)
    parser.add_argument("--output", "-o", help="output JSON path")
    args = parser.parse_args()

    devices = unique_by_ip(discover(timeout=args.timeout))
    host = args.ip
    if not host:
        if len(devices) != 1:
            print(
                f"found {len(devices)} device(s); pass --ip to choose one",
                file=sys.stderr,
            )
            return 1
        host = devices[0].ip

    client = YeelightClient(host, args.port, args.timeout)
    try:
        status = client.status()
    except YeelightError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()

    matched = next((device for device in devices if device.ip == host), None)
    payload = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "local_ipv4": local_ipv4(),
        "host": host,
        "port": args.port,
        "device": matched.as_dict() if matched else None,
        "status": status,
        "discovery": [device.as_dict() for device in devices],
    }

    output = Path(args.output) if args.output else (
        Path("captures") / f"device-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
