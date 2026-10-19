"""A small in-process emulator of a YLDP06YL / color2 bulb.

It is useful for developing the toolkit without hardware, for tests, and as
executable documentation of the LAN protocol. It implements the common command
set, SSDP discovery, state notifications and music mode.
"""

from __future__ import annotations

import argparse
import json
import socket
import socketserver
import struct
import threading
import time
from typing import Any

from .miio import HELLO_PACKET, MIIO_PORT, build_packet, parse_packet
from .protocol import CONTROL_PORT, SSDP_ADDRESS, SSDP_PORT, clamp, rgb_from_hsv

SUPPORT = (
    "get_prop set_default set_power toggle set_bright start_cf stop_cf set_scene "
    "cron_add cron_get cron_del set_ct_abx set_rgb set_hsv set_adjust adjust_bright "
    "adjust_ct adjust_color set_music set_name"
)

DEFAULT_STATE: dict[str, str] = {
    "power": "on",
    "bright": "100",
    "ct": "4000",
    "rgb": "16777215",
    "hue": "0",
    "sat": "0",
    "color_mode": "2",
    "flowing": "0",
    "delayoff": "0",
    "music_on": "0",
    "name": "Fake YLDP06YL",
    "fw_ver": "18",
    "model": "color2",
}


class _Handler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        bulb: FakeBulb = self.server.bulb  # type: ignore[attr-defined]
        bulb._register(self.request)
        try:
            while True:
                line = self.rfile.readline()
                if not line:
                    break
                if line.strip():
                    bulb._process_line(self.request, line)
        except (ConnectionError, OSError):
            pass
        finally:
            bulb._unregister(self.request)


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class FakeBulb:
    """Threaded fake bulb listening on a TCP port."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        model: str = "color2",
        name: str = "Fake YLDP06YL",
    ):
        self.host = host
        self.model = model
        self.state = dict(DEFAULT_STATE)
        self.state["model"] = model
        self.state["name"] = name
        self._lock = threading.RLock()
        self._clients: set[socket.socket] = set()
        self._music: tuple[str, int] | None = None
        self._server = _Server((host, port), _Handler)
        self._server.bulb = self  # type: ignore[attr-defined]
        self._thread: threading.Thread | None = None
        self._ssdp: FakeSSDP | None = None

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def address(self) -> tuple[str, int]:
        return self.host, self.port

    def start(self) -> "FakeBulb":
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="fake-yeelight",
            daemon=True,
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._ssdp is not None:
            self._ssdp.stop()
            self._ssdp = None
        self._server.shutdown()
        self._server.server_close()
        with self._lock:
            clients = list(self._clients)
            self._clients.clear()
        for conn in clients:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                conn.close()
            except OSError:
                pass
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)
        self._thread = None

    def enable_ssdp(self, port: int = 0) -> "FakeSSDP":
        self._ssdp = FakeSSDP(self, self.host, port)
        self._ssdp.start()
        return self._ssdp

    def __enter__(self) -> "FakeBulb":
        return self.start()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.stop()

    # --------------------------------------------------------------- internals

    def _register(self, conn: socket.socket) -> None:
        with self._lock:
            self._clients.add(conn)

    def _unregister(self, conn: socket.socket) -> None:
        with self._lock:
            self._clients.discard(conn)

    def _reply(self, conn: socket.socket, message_id: Any, payload: dict[str, Any]) -> None:
        message = {"id": message_id, **payload}
        data = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\r\n"
        try:
            conn.sendall(data)
        except OSError:
            self._unregister(conn)

    def _notify(self, changed: dict[str, str]) -> None:
        if not changed:
            return
        payload = (
            json.dumps(
                {"method": "props", "params": changed},
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\r\n"
        )
        with self._lock:
            clients = list(self._clients)
            music = self._music
        for conn in clients:
            try:
                conn.sendall(payload)
            except OSError:
                self._unregister(conn)
        if music and self.state.get("music_on") == "1":
            udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                udp.sendto(payload, music)
            except OSError:
                pass
            finally:
                udp.close()

    def _set(self, **props: Any) -> None:
        changed: dict[str, str] = {}
        with self._lock:
            for key, value in props.items():
                text = str(value)
                if self.state.get(key) != text:
                    self.state[key] = text
                    changed[key] = text
        self._notify(changed)

    def _process_line(self, conn: socket.socket, line: bytes) -> None:
        try:
            message = json.loads(line.decode("utf-8", "replace"))
            if not isinstance(message, dict):
                raise ValueError
        except (json.JSONDecodeError, ValueError):
            self._reply(conn, None, {"error": {"code": -1, "message": "invalid JSON"}})
            return

        message_id = message.get("id")
        method = message.get("method")
        params = message.get("params") or []
        if not isinstance(method, str) or not isinstance(params, list):
            self._reply(conn, message_id, {"error": {"code": -1, "message": "invalid message"}})
            return

        try:
            result = self._dispatch(conn, method, params)
        except ValueError as exc:
            self._reply(conn, message_id, {"error": {"code": -3, "message": str(exc)}})
            return
        except NotImplementedError:
            self._reply(
                conn,
                message_id,
                {"error": {"code": -4, "message": "method not supported"}},
            )
            return
        self._reply(conn, message_id, {"result": result})

    def _dispatch(self, conn: socket.socket, method: str, params: list[Any]) -> list[Any]:
        if method == "get_prop":
            with self._lock:
                return [self.state.get(str(key), "") for key in params]

        if method == "set_power":
            if not params:
                raise ValueError("set_power needs a value")
            value = str(params[0])
            if value not in ("on", "off"):
                raise ValueError("power must be 'on' or 'off'")
            mode = str(params[3]) if len(params) > 3 else None
            updates: dict[str, Any] = {"power": value}
            if mode is not None:
                updates["color_mode"] = mode
            self._set(**updates)
            return ["ok"]

        if method == "toggle":
            self._set(power="off" if self.state["power"] == "on" else "on")
            return ["ok"]

        if method == "set_bright":
            if not params:
                raise ValueError("set_bright needs a value")
            self._set(bright=clamp(int(params[0]), 1, 100))
            return ["ok"]

        if method == "set_ct_abx":
            if not params:
                raise ValueError("set_ct_abx needs a value")
            self._set(ct=clamp(int(params[0]), 1700, 6500), color_mode=1)
            return ["ok"]

        if method == "set_rgb":
            if not params:
                raise ValueError("set_rgb needs a value")
            self._set(rgb=clamp(int(params[0]), 0, 0xFFFFFF), color_mode=2)
            return ["ok"]

        if method == "set_hsv":
            if len(params) < 2:
                raise ValueError("set_hsv needs hue and saturation")
            hue = clamp(int(params[0]), 0, 359)
            sat = clamp(int(params[1]), 0, 100)
            self._set(hue=hue, sat=sat, rgb=rgb_from_hsv(hue, sat), color_mode=3)
            return ["ok"]

        if method == "set_scene":
            if not params:
                raise ValueError("set_scene needs a scene type")
            scene = str(params[0])
            if scene == "color" and len(params) >= 3:
                self._set(rgb=int(params[1]), bright=clamp(int(params[2]), 1, 100), color_mode=2)
            elif scene == "hsv" and len(params) >= 4:
                hue = clamp(int(params[1]), 0, 359)
                sat = clamp(int(params[2]), 0, 100)
                self._set(
                    hue=hue,
                    sat=sat,
                    bright=clamp(int(params[3]), 1, 100),
                    rgb=rgb_from_hsv(hue, sat),
                    color_mode=3,
                )
            elif scene == "ct" and len(params) >= 3:
                self._set(ct=clamp(int(params[1]), 1700, 6500), bright=clamp(int(params[2]), 1, 100), color_mode=1)
            elif scene == "cf":
                self._set(flowing=1)
            elif scene == "auto_delay_off" and len(params) >= 3:
                self._set(delayoff=int(params[2]), bright=clamp(int(params[1]), 1, 100))
            else:
                raise ValueError("unsupported scene")
            return ["ok"]

        if method == "start_cf":
            if len(params) < 3:
                raise ValueError("start_cf needs count, action and expression")
            self._set(flowing=1)
            return ["ok"]

        if method == "stop_cf":
            self._set(flowing=0)
            return ["ok"]

        if method == "set_name":
            if not params:
                raise ValueError("set_name needs a value")
            self._set(name=str(params[0]))
            return ["ok"]

        if method == "set_music":
            if not params:
                raise ValueError("set_music needs an action")
            action = int(params[0])
            if action == 1:
                if len(params) < 3:
                    raise ValueError("set_music 1 needs host and port")
                with self._lock:
                    self._music = (str(params[1]), int(params[2]))
                self._set(music_on=1)
            else:
                with self._lock:
                    self._music = None
                self._set(music_on=0)
            return ["ok"]

        if method in ("set_adjust", "adjust_bright", "adjust_ct", "adjust_color"):
            return ["ok"]

        if method in ("cron_add", "cron_get", "cron_del", "set_default"):
            return ["ok"]

        raise NotImplementedError(method)


class FakeSSDP:
    """Minimal SSDP responder for the fake bulb."""

    def __init__(self, bulb: FakeBulb, host: str = "127.0.0.1", port: int = 0):
        self.bulb = bulb
        self.host = host
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        bind_host = "0.0.0.0" if int(port) == SSDP_PORT else host
        self._sock.bind((bind_host, int(port)))
        if int(port) == SSDP_PORT:
            try:
                membership = socket.inet_aton(SSDP_ADDRESS) + socket.inet_aton("0.0.0.0")
                self._sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, membership)
            except OSError:
                pass
        self._sock.settimeout(0.5)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return int(self._sock.getsockname()[1])

    def start(self) -> "FakeSSDP":
        self._thread = threading.Thread(target=self._loop, name="fake-ssdp", daemon=True)
        self._thread.start()
        return self

    def _response(self) -> bytes:
        state = self.bulb.state
        headers = {
            "Cache-Control": "max-age=3600",
            "Location": f"yeelight://{self.bulb.host}:{self.bulb.port}",
            "Server": "POSIX UPnP/1.0 YGLC/1",
            "id": "0x0000000000000001",
            "model": state["model"],
            "fw_ver": state["fw_ver"],
            "support": SUPPORT,
            "power": state["power"],
            "bright": state["bright"],
            "color_mode": state["color_mode"],
            "ct": state["ct"],
            "rgb": state["rgb"],
            "hue": state["hue"],
            "sat": state["sat"],
            "name": state["name"],
        }
        lines = ["HTTP/1.1 200 OK"] + [f"{key}: {value}" for key, value in headers.items()]
        return ("\r\n".join(lines) + "\r\n\r\n").encode("utf-8")

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                payload, address = self._sock.recvfrom(65535)
            except TimeoutError:
                continue
            except OSError:
                return
            if b"M-SEARCH" in payload.upper():
                try:
                    self._sock.sendto(self._response(), address)
                except OSError:
                    pass

    def stop(self) -> None:
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)


class FakeMiio:
    """Minimal miIO responder (UDP 54321) for the fake bulb.

    By default it leaks its token in the handshake, like older firmware. Set
    ``expose_token=False`` to emulate firmware that returns an all-zero token.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 0,
        token: bytes | None = None,
        expose_token: bool = True,
        lan_enabled: bool = False,
    ):
        self.host = host
        self.token = token or bytes.fromhex("00112233445566778899aabbccddeeff")
        self.expose_token = expose_token
        self.lan_enabled = lan_enabled
        self.device_id = 0x12345678
        self.requests: list[dict[str, Any]] = []
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, int(port)))
        self._sock.settimeout(0.5)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return int(self._sock.getsockname()[1])

    def start(self) -> "FakeMiio":
        self._thread = threading.Thread(target=self._loop, name="fake-miio", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)
        self._thread = None

    def _hello_reply(self) -> bytes:
        stamp = int(time.time()) & 0xFFFFFFFF
        token = self.token if self.expose_token else b"\x00" * 16
        return struct.pack(">HHIII", 0x2131, 32, 0, self.device_id, stamp) + token

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                payload, address = self._sock.recvfrom(4096)
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                return
            if len(payload) >= 4 and payload[:4] == HELLO_PACKET[:4] and len(payload) == 32:
                try:
                    self._sock.sendto(self._hello_reply(), address)
                except OSError:
                    pass
                continue
            try:
                request = parse_packet(payload, self.token)
            except Exception:
                # A real device silently ignores packets it cannot authenticate.
                continue
            self.requests.append(request)
            method = request.get("method")
            params = request.get("params") or []
            result: list[Any] = ["ok"]
            if method == "miio.info":
                result = ["color2"]
            elif method == "set_ps" and list(params)[:2] == ["cfg_lan_ctrl", "1"]:
                self.lan_enabled = True
            response = {"id": request.get("id"), "result": result}
            stamp = (int(time.time()) + 1) & 0xFFFFFFFF
            packet = build_packet(
                self.device_id.to_bytes(4, "big"), stamp, self.token, response
            )
            try:
                self._sock.sendto(packet, address)
            except OSError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Fake Yeelight YLDP06YL bulb")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=CONTROL_PORT)
    parser.add_argument("--name", default="Fake YLDP06YL")
    parser.add_argument("--ssdp", action="store_true", help="also answer SSDP discovery")
    parser.add_argument("--ssdp-port", type=int, default=SSDP_PORT)
    parser.add_argument("--miio", action="store_true", help="also answer miIO on UDP 54321")
    parser.add_argument("--miio-port", type=int, default=MIIO_PORT)
    args = parser.parse_args()

    bulb = FakeBulb(args.host, args.port, name=args.name).start()
    ssdp = None
    miio = None
    if args.ssdp:
        try:
            ssdp = bulb.enable_ssdp(args.ssdp_port)
        except OSError as exc:
            print(f"SSDP disabled: {exc}")
    if args.miio:
        try:
            miio = FakeMiio(args.host, args.miio_port).start()
        except OSError as exc:
            print(f"miIO disabled: {exc}")
    print(f"Fake bulb listening on {bulb.host}:{bulb.port}")
    if ssdp is not None:
        print(f"SSDP responder on {ssdp.host}:{ssdp.port} (tests only)")
    if miio is not None:
        print(f"miIO responder on {miio.host}:{miio.port} (token exposed in handshake)")
    print("Try: python -m yeelight_re status --ip " + bulb.host)
    print("Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopping.")
    finally:
        if miio is not None:
            miio.stop()
        bulb.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
