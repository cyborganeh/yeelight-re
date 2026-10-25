"""Command-line interface for local Yeelight control."""

from __future__ import annotations

import argparse
import colorsys
import ipaddress
import json
import math
import os
import subprocess
import sys
import time
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Sequence

from .client import MusicMode, YeelightClient, parse_json_argument
from .discovery import (
    BulbHit,
    discover,
    format_device,
    local_ipv4,
    probe_port,
    scan_lan,
    unique_by_ip,
)
from .miio import MIIO_PORT
from .presets import SCENES, FLOW_PRESETS, flow_params, scene_params
from .protocol import (
    CONTROL_PORT,
    DEFAULT_TIMEOUT,
    Device,
    YeelightError,
    clamp,
    parse_rgb,
    rgb_components,
    rgb_to_hex,
)

VERSION = "0.3.0"


# --------------------------------------------------------------------- helpers


def _add_common(parser: argparse.ArgumentParser, host: bool = True, json_flag: bool = True) -> None:
    if host:
        parser.add_argument("--ip", help="bulb IPv4 address (or set YEELIGHT_IP)")
        parser.add_argument("--port", type=int, default=CONTROL_PORT, help="control TCP port")
        parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="request timeout")
    if json_flag:
        parser.add_argument("--json", action="store_true", help="machine-readable output")


def _program() -> str:
    """How the user should invoke this tool (source tree vs frozen EXE)."""
    return "yeelight-re.exe" if getattr(sys, "frozen", False) else "python -m yeelight_re"


def _resolve_host(args: argparse.Namespace) -> str:
    host = getattr(args, "ip", None) or os.environ.get("YEELIGHT_IP")
    if host:
        return host
    devices = discover(timeout=2.0)
    if not devices:
        raise YeelightError(
            "no bulb found. Pass --ip, set YEELIGHT_IP, or enable LAN Control in the app."
        )
    if len(devices) > 1:
        listing = ", ".join(f"{device.ip} ({device.name or device.model})" for device in devices)
        raise YeelightError(f"multiple bulbs found: {listing}; pass --ip")
    return devices[0].ip


def _client(args: argparse.Namespace) -> YeelightClient:
    return YeelightClient(_resolve_host(args), getattr(args, "port", CONTROL_PORT), args.timeout)


def _emit(args: argparse.Namespace, payload: Any, human: str) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(human)


def _ok(args: argparse.Namespace, message: str, result: Any = None) -> int:
    _emit(args, {"ok": True, "result": result if result is not None else ["ok"]}, message)
    return 0


def _print_status(status: dict[str, Any]) -> str:
    rgb = status.get("rgb")
    rgb_text = ""
    if isinstance(rgb, int):
        red, green, blue = rgb_components(rgb)
        rgb_text = f"{rgb_to_hex(rgb)} ({red},{green},{blue})"
    mode = status.get("color_mode")
    mode_text = {0: "normal", 1: "color temperature", 2: "RGB", 3: "HSV"}.get(mode, str(mode))
    lines = [
        f"Power        : {status.get('power', '?')}",
        f"Brightness   : {status.get('bright', '?')}%",
        f"Color mode   : {mode_text}",
        f"RGB          : {rgb_text or '?'}",
        f"HSV          : {status.get('hue', '?')}, {status.get('sat', '?')}%",
        f"Temperature  : {status.get('ct', '?')} K",
        f"Name         : {status.get('name', '') or '(empty)'}",
        f"Flow running : {'yes' if str(status.get('flowing')) == '1' else 'no'}",
        f"Music mode   : {'yes' if str(status.get('music_on')) == '1' else 'no'}",
    ]
    return "\n".join(lines)


def _print_device(device: Device, index: int | None = None) -> str:
    position = f"[{index}] " if index is not None else ""
    support = f"{len(device.support)} methods" if device.support else "tidak diketahui"
    return (
        f"{position}{device.ip}:{device.port}\n"
        f"     model   : {device.model or '?'}\n"
        f"     firmware: {device.fw_ver or '?'}\n"
        f"     name    : {device.name or '(empty)'}\n"
        f"     support : {support}"
    )


# -------------------------------------------------------------------- commands


def cmd_discover(args: argparse.Namespace) -> int:
    devices = unique_by_ip(discover(timeout=args.timeout))
    scanned: list[BulbHit] = []
    if args.scan:
        # SSDP is cheap but many routers drop multicast, so a subnet scan runs
        # as a fallback when nothing answered.
        scanned = scan_lan(
            args.subnet,
            timeout=args.scan_timeout,
            workers=args.workers,
        )
        known = {device.ip for device in devices}
        for hit in scanned:
            if hit.is_bulb and hit.ip not in known:
                devices.append(
                    Device(
                        ip=hit.ip,
                        port=hit.port,
                        model=hit.model,
                        name=hit.name,
                        power=hit.power,
                        bright=hit.bright,
                    )
                )
                known.add(hit.ip)
        devices.sort(key=lambda item: ipaddress.ip_address(item.ip))

    if args.json:
        print(
            json.dumps(
                {
                    "devices": [device.as_dict() for device in devices],
                    "scan": [hit.as_dict() for hit in scanned],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    if devices:
        print(f"Found {len(devices)} Yeelight device(s):\n")
        for index, device in enumerate(devices, start=1):
            print(_print_device(device, index))
            print()
    else:
        print("No Yeelight device answered SSDP.")

    if scanned:
        print(f"Subnet scan (TCP {CONTROL_PORT}):")
        for hit in scanned:
            print(f"  {hit.label}")

    if not devices:
        print(
            "\nChecklist:\n"
            "  1. Bulb is powered and on the same L2 network (2.4 GHz Wi-Fi).\n"
            "  2. LAN Control / Developer Mode is enabled in the Yeelight app.\n"
            "  3. Windows firewall allows UDP replies from the bulb.\n"
            f"  4. IP berubah? Jalankan: {_program()} scan"
        )
    return 0


def cmd_scan(args: argparse.Namespace) -> int:
    hits = scan_lan(
        args.subnet,
        timeout=args.connect_timeout,
        workers=args.workers,
        identify_timeout=args.identify_timeout,
    )
    bulbs = [hit for hit in hits if hit.is_bulb]
    others = [hit for hit in hits if not hit.is_bulb]

    if args.json:
        print(
            json.dumps(
                {
                    "bulbs": [hit.as_dict() for hit in bulbs],
                    "open_ports": [hit.as_dict() for hit in others],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    if bulbs:
        print(f"Lampu Yeelight ditemukan: {len(bulbs)}\n")
        for hit in bulbs:
            print(f"  {hit.label}")
            print(
                f"     model {hit.model or '?'} | power {hit.power or '?'} | "
                f"bright {hit.bright if hit.bright is not None else '?'}% | "
                f"name {hit.name or '(kosong)'}"
            )
        if len(bulbs) == 1:
            print(f"\nPakai: {_program()} status --ip {bulbs[0].ip}")
        else:
            print("\nPilih salah satu IP di atas untuk --ip.")
    else:
        print(f"Tidak ada lampu Yeelight yang menjawab di subnet ini.")

    if others:
        print(f"\nHost lain dengan TCP {CONTROL_PORT} terbuka (bukan Yeelight):")
        for hit in others:
            print(f"  {hit.ip}:{hit.port}  {hit.error or 'tidak menjawab get_prop'}")

    if not hits:
        print(
            "Pastikan PC dan lampu berada di jaringan yang sama. "
            "Coba tentukan subnet manual: --subnet 192.168.1.0/24"
        )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        status = client.status()
    finally:
        client.close()
    _emit(args, status, _print_status(status))
    return 0


def cmd_power(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        if args.command == "toggle":
            result = client.toggle()
        else:
            result = client.set_power(
                args.command == "on", args.effect, args.duration
            )
    finally:
        client.close()
    return _ok(args, f"Power: {args.command}", result)


def cmd_bright(args: argparse.Namespace) -> int:
    value = clamp(args.value, 1, 100)
    client = _client(args)
    try:
        result = client.set_bright(value, args.effect, args.duration)
    finally:
        client.close()
    return _ok(args, f"Brightness: {value}%", result)


def cmd_color(args: argparse.Namespace) -> int:
    rgb = parse_rgb(args.value)
    client = _client(args)
    try:
        if args.bright is not None:
            brightness = clamp(args.bright, 1, 100)
            result = client.set_scene("color", rgb, brightness)
            message = f"Color: {rgb_to_hex(rgb)} at {brightness}%"
        else:
            result = client.set_rgb(rgb, args.effect, args.duration)
            message = f"Color: {rgb_to_hex(rgb)}"
    finally:
        client.close()
    return _ok(args, message, result)


def cmd_ct(args: argparse.Namespace) -> int:
    kelvin = clamp(args.value, 1700, 6500)
    client = _client(args)
    try:
        if args.bright is not None:
            brightness = clamp(args.bright, 1, 100)
            result = client.set_scene("ct", kelvin, brightness)
            message = f"Color temperature: {kelvin} K at {brightness}%"
        else:
            result = client.set_ct(kelvin, args.effect, args.duration)
            message = f"Color temperature: {kelvin} K"
    finally:
        client.close()
    return _ok(args, message, result)


def cmd_hsv(args: argparse.Namespace) -> int:
    hue = clamp(args.hue, 0, 359)
    sat = clamp(args.sat, 0, 100)
    client = _client(args)
    try:
        result = client.set_hsv(hue, sat, args.effect, args.duration)
    finally:
        client.close()
    return _ok(args, f"HSV: {hue}, {sat}%", result)


def cmd_scene(args: argparse.Namespace) -> int:
    if args.list:
        for name, params in sorted(SCENES.items()):
            print(f"{name:10s} set_scene {list(params)}")
        return 0
    params = scene_params(args.name)
    client = _client(args)
    try:
        result = client.set_scene(*params)
    finally:
        client.close()
    return _ok(args, f"Scene: {args.name} {list(params)}", result)


def cmd_flow(args: argparse.Namespace) -> int:
    if args.list:
        for name, (count, action, expression) in sorted(FLOW_PRESETS.items()):
            print(f"{name:10s} count={count} action={action}")
            print(f"           {expression}")
        return 0

    if args.expression:
        expression = args.expression
        count = args.count if args.count is not None else 0
        action = args.action if args.action is not None else 1
    elif args.preset:
        count, action, expression = flow_params(args.preset)
        if args.count is not None:
            count = args.count
        if args.action is not None:
            action = args.action
    else:
        raise ValueError("provide a preset name or --expression")

    client = _client(args)
    try:
        result = client.start_flow(count, action, expression)
    finally:
        client.close()
    return _ok(args, f"Flow started (count={count}, action={action})", result)


def cmd_name(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        result = client.set_name(args.value)
    finally:
        client.close()
    return _ok(args, f"Name set to: {args.value}", result)


def cmd_listen(args: argparse.Namespace) -> int:
    client = _client(args)
    try:
        print(f"Listening for notifications from {client.host}:{client.port} (Ctrl+C to stop)...")
        for props in client.iter_notifications(timeout=args.seconds):
            stamp = datetime.now().strftime("%H:%M:%S")
            pretty = json.dumps(props, ensure_ascii=False)
            print(f"{stamp}  {pretty}")
    except KeyboardInterrupt:
        pass
    finally:
        client.close()
    return 0


def cmd_music(args: argparse.Namespace) -> int:
    client = _client(args)
    fps = max(1.0, min(60.0, args.fps))
    frames = max(1, int(args.seconds * fps))
    try:
        with MusicMode(client) as music:
            print(
                f"Music mode active: UDP {music.local_ip}:{music.port}, "
                f"{fps:.0f} fps for {args.seconds:.1f}s. Ctrl+C to stop."
            )
            started = time.monotonic()
            try:
                for frame in range(frames):
                    if args.mode == "rainbow":
                        hue = (frame * 360.0 / max(1, fps * 2)) % 360.0
                        red, green, blue = colorsys.hsv_to_rgb(hue / 360.0, 1.0, 1.0)
                    elif args.mode == "pulse":
                        level = 0.15 + 0.85 * (0.5 + 0.5 * math.sin(frame / max(1.0, fps)))
                        red, green, blue = colorsys.hsv_to_rgb(0.08, 0.7, level)
                    else:
                        red = green = blue = clamp(args.value, 1, 100) / 100.0
                    rgb = (
                        (round(red * 255) << 16)
                        | (round(green * 255) << 8)
                        | round(blue * 255)
                    )
                    client.set_rgb(rgb, "sudden", 0)
                    sleep_for = started + (frame + 1) / fps - time.monotonic()
                    if sleep_for > 0:
                        time.sleep(sleep_for)
                print("Done.")
            except KeyboardInterrupt:
                print("\nStopped.")
            drained = 0
            while music.get(timeout=0.01) is not None:
                drained += 1
            if drained:
                print(f"Received {drained} UDP notification(s).")
    finally:
        client.close()
    return 0


def cmd_miio(args: argparse.Namespace) -> int:
    from .miio import enable_lan_control, probe, provision_wifi

    if getattr(args, "wifi_ssid", None):
        report = provision_wifi(
            host=args.ip,
            ssid=args.wifi_ssid,
            password=getattr(args, "wifi_pass", ""),
            token=args.token,
            port=args.miio_port,
            timeout=args.timeout,
            enable_lan=True,
        )
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            print(f"miIO {args.ip}:{args.miio_port}: Wi-Fi provisioning")
            print(f"Device ID : 0x{report['device_id']}")
            print(f"SSID      : {args.wifi_ssid}")
            print(f"LAN Ctrl  : {report.get('lan_control_result', 'skipped')}")
            print(f"Result    : {report.get('result')}")
            print("\nProvisioning OK! Hotspot lampu akan mati dan lampu bergabung ke Wi-Fi rumah.")
            print("Pastikan PC tersambung ke Wi-Fi yang sama, lalu scan dengan:")
            print(f"  {_program()} scan")
        return 0

    if args.enable:
        report = enable_lan_control(
            args.ip,
            token=args.token,
            port=args.miio_port,
            control_port=args.port,
            timeout=args.timeout,
        )
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            print(f"miIO {args.ip}:{args.miio_port}: handshake OK")
            print(f"Device ID : 0x{report['device_id']}")
            print(f"Token     : {'dari handshake' if report['token_exposed'] else 'dari --token'}")
            print(f"set_ps    : {report['result']}")
            print(f"TCP {report['control_port']}: {'OK' if report['lan_control'] else 'masih tertutup'}")
            if report["lan_control"]:
                print("\nLAN Control aktif. Coba sekarang:")
                print(f"  {_program()} doctor --ip {args.ip}")
            else:
                print(
                    "\nPerintah diterima, tetapi port kontrol belum terbuka. "
                    "Firmware ini mungkin memakai nama parameter lain atau "
                    "menolak perubahan dari miIO."
                )
                print("Lihat docs/TANPA-LOGIN.md (Jalur B).")
        return 0 if report["lan_control"] else 1

    info = probe(args.ip, args.miio_port, args.timeout)
    if args.json:
        print(json.dumps(info, indent=2, ensure_ascii=False))
        return 0 if info["available"] else 1
    if not info["available"]:
        print(f"miIO {args.ip}:{args.miio_port}: tidak menjawab")
        print(f"  {info['error']}")
        return 1
    print(f"miIO {args.ip}:{args.miio_port}: OK")
    print(f"Device ID : 0x{info['device_id']}")
    if info["token_exposed"]:
        print(f"Token     : {info['token']}  (bocor lewat handshake)")
        print("\nFirmware ini masih membocorkan token. Untuk mencoba membuka LAN Control:")
        print(f"  {_program()} miio --ip {args.ip} --enable")
    else:
        print("Token     : tidak dibocorkan (firmware mengembalikan 0x00)")
        print(
            "\nTanpa token, perintah miIO tidak bisa dikirim. "
            "Coba --token <32 hex> jika kamu punya token perangkat ini."
        )
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    print(f"Local IPv4: {local_ipv4() or 'unknown'}")
    devices = unique_by_ip(discover(timeout=args.timeout))
    if devices:
        print(f"SSDP: OK ({len(devices)} device(s))")
        for device in devices:
            print("  " + format_device(device))
    else:
        print("SSDP: no reply (multicast blocked, LAN Control off, or different subnet)")

    host = args.ip or (devices[0].ip if len(devices) == 1 else None)
    if not host:
        if len(devices) > 1:
            print("\nMultiple devices found; run again with --ip <address>.")
        else:
            print("\nNo target. Pass --ip <address> or fix discovery first.")
        return 1

    print(f"\nTarget: {host}:{args.port}")
    open_port, reason = probe_port(host, args.port, timeout=args.timeout)
    if not open_port:
        print(f"TCP {args.port}: FAIL - {reason}")
        from .miio import probe as miio_probe

        info = miio_probe(host, timeout=min(2.0, args.timeout))
        if info["available"]:
            print(f"miIO UDP 54321: OK (device 0x{info['device_id']})")
            if info["token_exposed"]:
                print("Token miIO: tersedia lewat handshake")
                print(f"  Coba tanpa app: {_program()} miio --ip {host} --enable")
            else:
                print("Token miIO: tidak tersedia (firmware tidak membocorkannya)")
        else:
            print("miIO UDP 54321: tidak menjawab handshake")
        print(
            "\nThis is the usual sign that LAN Control / Developer Mode is OFF.\n"
            "Open the Yeelight app once, enable it, then retry. See docs/TANPA-LOGIN.md."
        )
        return 1
    print(f"TCP {args.port}: OK")

    client = YeelightClient(host, args.port, args.timeout)
    try:
        status = client.status()
        print("\nLAN API: OK")
        print(_print_status(status))
        matched = next((device for device in devices if device.ip == host), None)
        if matched:
            print(f"\nModel: {matched.model}  firmware: {matched.fw_ver}")
            print(f"Support ({len(matched.support)}): {' '.join(matched.support)}")
            if "set_music" in matched.support:
                print("Music mode: supported")
            if "set_rgb" in matched.support:
                print("Color control: supported")
    finally:
        client.close()
    return 0


def cmd_web(args: argparse.Namespace) -> int:
    from .web import serve

    host = _resolve_host(args)
    client = YeelightClient(host, args.port, args.timeout)
    url = f"http://{'127.0.0.1' if args.bind in ('0.0.0.0', '') else args.bind}:{args.web_port}/"
    if args.open:
        import threading

        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    print(f"Yeelight local dashboard: {url}")
    print("No account, no cloud. Press Ctrl+C to stop.")
    try:
        serve(client, args.bind, args.web_port)
    finally:
        client.close()
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    argv: list[str] = []
    ip = args.ip or os.environ.get("YEELIGHT_IP")
    if ip:
        argv += ["--ip", ip]
    if args.port:
        argv += ["--port", str(args.port)]
    try:
        from .gui import main as gui_main
    except ImportError:
        # The console build excludes Tkinter to stay small; hand over to the
        # GUI executable that ships next to it.
        sibling = Path(sys.executable).with_name("yeelight-re-gui.exe")
        if getattr(sys, "frozen", False) and sibling.is_file():
            print(f"Membuka {sibling.name}...")
            subprocess.Popen([str(sibling), *argv])
            return 0
        raise YeelightError(
            "Tkinter is not available in this Python build; "
            "run yeelight-re-gui.exe instead"
        )
    return int(gui_main(argv) or 0)


def cmd_raw(args: argparse.Namespace) -> int:
    if args.params_json:
        params = parse_json_argument(args.params_json)
    else:
        params = list(args.params)
    client = _client(args)
    try:
        result = client.raw(args.method, params)
    finally:
        client.close()
    _emit(args, {"method": args.method, "params": params, "result": result}, json.dumps(result))
    return 0


def cmd_dump(args: argparse.Namespace) -> int:
    devices = unique_by_ip(discover(timeout=args.timeout))
    host = args.ip or os.environ.get("YEELIGHT_IP")
    if not host:
        if len(devices) != 1:
            raise YeelightError("pass --ip when zero or multiple bulbs are discovered")
        host = devices[0].ip
    client = YeelightClient(host, args.port, args.timeout)
    try:
        status = client.status()
    finally:
        client.close()
    payload = {
        "host": host,
        "port": args.port,
        "status": status,
        "discovered": [device.as_dict() for device in devices],
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
        print(f"Wrote {args.output}")
    else:
        print(text)
    return 0


def cmd_repl(args: argparse.Namespace) -> int:
    client = _client(args)
    print(
        "Commands: status | on | off | toggle | bright N | color #RRGGBB | ct K | "
        "props [key ...] | raw METHOD [JSON_ARRAY] | quit"
    )
    try:
        while True:
            try:
                line = input("yeelight> ").strip()
            except EOFError:
                break
            if not line:
                continue
            if line in ("quit", "exit"):
                break
            parts = line.split()
            command = parts[0].lower()
            try:
                if command == "status":
                    print(_print_status(client.status()))
                elif command in ("on", "off"):
                    print(client.set_power(command == "on"))
                elif command == "toggle":
                    print(client.toggle())
                elif command == "bright":
                    print(client.set_bright(int(parts[1])))
                elif command == "color":
                    print(client.set_rgb(parse_rgb(parts[1])))
                elif command == "ct":
                    print(client.set_ct(int(parts[1])))
                elif command == "props":
                    print(client.get_props(parts[1:] or None))
                elif command == "raw":
                    method = parts[1]
                    params = parse_json_argument(" ".join(parts[2:])) if len(parts) > 2 else []
                    print(client.send(method, params))
                elif command == "help":
                    print("status | on | off | toggle | bright N | color #RRGGBB | ct K | props | raw | quit")
                else:
                    print(f"unknown command: {command}")
            except (IndexError, ValueError, YeelightError) as exc:
                print(f"error: {exc}")
    except KeyboardInterrupt:
        print()
    finally:
        client.close()
    return 0


# ---------------------------------------------------------------------- parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yeelight-re",
        description="Local, account-free toolkit for Yeelight YLDP06YL / color2 bulbs.",
        epilog="See README.md and docs/ for the protocol and no-login paths.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("discover", help="find bulbs with SSDP")
    _add_common(p, host=False)
    p.add_argument("--timeout", type=float, default=3.0)
    p.add_argument("--scan", action="store_true", help="also scan the local subnet")
    p.add_argument("--subnet", help="subnet for --scan, e.g. 192.168.1.0/24")
    p.add_argument("--scan-timeout", type=float, default=0.25)
    p.add_argument("--workers", type=int, default=128, help="parallel probes")
    p.set_defaults(func=cmd_discover)

    p = sub.add_parser(
        "scan",
        help="scan a subnet and identify every bulb (use when the IP changed)",
    )
    _add_common(p, host=False)
    p.add_argument("--subnet", help="subnet, default: every local /24")
    p.add_argument("--connect-timeout", type=float, default=0.25)
    p.add_argument("--identify-timeout", type=float, default=2.0)
    p.add_argument("--workers", type=int, default=128)
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("status", help="read power, brightness, colour and name")
    _add_common(p)
    p.set_defaults(func=cmd_status)

    for name, help_text in (("on", "turn on"), ("off", "turn off"), ("toggle", "toggle power")):
        p = sub.add_parser(name, help=help_text)
        _add_common(p)
        p.add_argument("--effect", choices=("smooth", "sudden"), default="smooth")
        p.add_argument("--duration", type=int, default=300, help="transition in ms")
        p.set_defaults(func=cmd_power)

    p = sub.add_parser("bright", help="set brightness 1-100")
    _add_common(p)
    p.add_argument("value", type=int)
    p.add_argument("--effect", choices=("smooth", "sudden"), default="smooth")
    p.add_argument("--duration", type=int, default=300)
    p.set_defaults(func=cmd_bright)

    p = sub.add_parser("color", help="set RGB colour (#RRGGBB, r,g,b or integer)")
    _add_common(p)
    p.add_argument("value")
    p.add_argument("--bright", type=int, help="also set brightness (uses set_scene)")
    p.add_argument("--effect", choices=("smooth", "sudden"), default="smooth")
    p.add_argument("--duration", type=int, default=300)
    p.set_defaults(func=cmd_color)

    p = sub.add_parser("ct", help="set colour temperature 1700-6500 K")
    _add_common(p)
    p.add_argument("value", type=int)
    p.add_argument("--bright", type=int, help="also set brightness (uses set_scene)")
    p.add_argument("--effect", choices=("smooth", "sudden"), default="smooth")
    p.add_argument("--duration", type=int, default=300)
    p.set_defaults(func=cmd_ct)

    p = sub.add_parser("hsv", help="set hue/saturation")
    _add_common(p)
    p.add_argument("hue", type=int)
    p.add_argument("sat", type=int)
    p.add_argument("--effect", choices=("smooth", "sudden"), default="smooth")
    p.add_argument("--duration", type=int, default=300)
    p.set_defaults(func=cmd_hsv)

    p = sub.add_parser("scene", help="apply a preset scene")
    _add_common(p)
    p.add_argument("name", nargs="?", help=", ".join(sorted(SCENES)))
    p.add_argument("--list", action="store_true")
    p.set_defaults(func=cmd_scene)

    p = sub.add_parser("flow", help="run a colour flow / animation")
    _add_common(p)
    p.add_argument("preset", nargs="?", help=", ".join(sorted(FLOW_PRESETS)))
    p.add_argument("--expression", help="raw flow expression")
    p.add_argument("--count", type=int, help="loops; 0 = infinite")
    p.add_argument("--action", type=int, choices=(0, 1, 2), help="0 recover, 1 stay, 2 turn off")
    p.add_argument("--list", action="store_true")
    p.set_defaults(func=cmd_flow)

    p = sub.add_parser("name", help="rename the bulb")
    _add_common(p)
    p.add_argument("value")
    p.set_defaults(func=cmd_name)

    p = sub.add_parser("listen", help="print state notifications")
    _add_common(p)
    p.add_argument("--seconds", type=float, help="stop after N seconds")
    p.set_defaults(func=cmd_listen)

    p = sub.add_parser("music", help="low-latency music mode demo")
    _add_common(p)
    p.add_argument("--seconds", type=float, default=10.0)
    p.add_argument("--fps", type=float, default=25.0)
    p.add_argument("--mode", choices=("rainbow", "pulse", "white"), default="rainbow")
    p.add_argument("--value", type=int, default=100, help="white level for --mode white")
    p.set_defaults(func=cmd_music)

    p = sub.add_parser("doctor", help="diagnose discovery, port and LAN API")
    _add_common(p)
    p.set_defaults(func=cmd_doctor)

    p = sub.add_parser(
        "miio",
        help="experimental: enable LAN Control over miIO UDP 54321 (no app)",
    )
    p.add_argument("--ip", required=True, help="bulb IPv4 address")
    p.add_argument("--token", help="32 hex chars, only if the handshake hides the token")
    p.add_argument("--miio-port", type=int, default=MIIO_PORT, help="miIO UDP port")
    p.add_argument("--port", type=int, default=CONTROL_PORT, help="control TCP port to verify")
    p.add_argument("--timeout", type=float, default=3.0, help="UDP timeout in seconds")
    p.add_argument("--enable", action="store_true", help="send set_ps cfg_lan_ctrl=1")
    p.add_argument("--wifi-ssid", help="Wi-Fi SSID to provision to bulb in AP mode")
    p.add_argument("--wifi-pass", default="", help="Wi-Fi password to provision")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    p.set_defaults(func=cmd_miio)

    p = sub.add_parser(
        "wifi-setup",
        help="provision Wi-Fi to a reset bulb in AP mode (default 192.168.10.1)",
    )
    p.add_argument("--ip", default="192.168.10.1", help="bulb IP in AP mode (default 192.168.10.1)")
    p.add_argument("--ssid", required=True, help="Wi-Fi SSID (2.4 GHz)")
    p.add_argument("--password", default="", help="Wi-Fi password")
    p.add_argument("--token", help="32 hex token (optional if leaked)")
    p.add_argument("--timeout", type=float, default=3.0)
    p.add_argument("--json", action="store_true")
    p.set_defaults(
        func=lambda args: cmd_miio(
            argparse.Namespace(
                ip=args.ip,
                wifi_ssid=args.ssid,
                wifi_pass=args.password,
                token=args.token,
                miio_port=MIIO_PORT,
                timeout=args.timeout,
                json=args.json,
            )
        )
    )

    p = sub.add_parser("gui", help="open the desktop GUI (Tkinter)")
    p.add_argument("--ip", help="pre-fill this bulb IPv4 address (or set YEELIGHT_IP)")
    p.add_argument("--port", type=int, default=CONTROL_PORT, help="pre-fill the control TCP port")
    p.set_defaults(func=cmd_gui)

    p = sub.add_parser("web", help="start a local dashboard (no cloud)")
    _add_common(p)
    p.add_argument("--bind", default="127.0.0.1", help="listen address")
    p.add_argument("--web-port", type=int, default=8765)
    p.add_argument("--open", action="store_true", help="open the browser")
    p.set_defaults(func=cmd_web)

    p = sub.add_parser("raw", help="send any protocol method (RE)")
    _add_common(p)
    p.add_argument("method")
    p.add_argument("params", nargs="*", help="string params")
    p.add_argument("--params-json", help="JSON array for numeric params")
    p.set_defaults(func=cmd_raw)

    p = sub.add_parser("dump", help="save discovery + status as JSON")
    _add_common(p)
    p.add_argument("--output", "-o")
    p.set_defaults(func=cmd_dump)

    p = sub.add_parser("repl", help="interactive local shell")
    _add_common(p)
    p.set_defaults(func=cmd_repl)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        # Double-clicking the EXE should show something readable instead of an
        # argparse error that instantly closes the console window.
        parser.print_help()
        if getattr(sys, "frozen", False):
            try:
                input("\nTekan Enter untuk keluar...")
            except (EOFError, KeyboardInterrupt):
                pass
        return 0
    args = parser.parse_args(arguments)
    handler: Callable[[argparse.Namespace], int] = args.func
    try:
        return int(handler(args) or 0)
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130
    except (YeelightError, ValueError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
