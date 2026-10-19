"""Experimental miIO client used to switch on LAN Control without the app.

Yeelight bulbs expose a second, older Xiaomi protocol on UDP ``54321``. This
module implements just enough of it to:

1. perform the 32-byte "hello" handshake,
2. recover the device token if the firmware still leaks it in the reply,
3. send ``set_ps ["cfg_lan_ctrl", "1"]`` to open TCP ``55443``.

Everything here is best-effort reverse engineering. Many firmware versions
answer the handshake but return an all-zero token, in which case a token has to
come from somewhere else. Nothing in this module talks to the cloud.
"""

from __future__ import annotations

import hashlib
import json
import socket
import struct
import time
from dataclasses import dataclass
from typing import Any, Sequence

from ._aes import AES128
from .discovery import probe_port
from .protocol import CONTROL_PORT, YeelightError

MIIO_PORT = 54321
MIIO_TIMEOUT = 3.0
MAGIC = 0x2131
HELLO_PACKET = bytes.fromhex("21310020" + "ff" * 28)
ZERO_TOKEN = b"\x00" * 16
EMPTY_TOKEN = b"\xff" * 16


class MiioError(YeelightError):
    """Base class for miIO failures."""


class MiioUnavailable(MiioError):
    """UDP 54321 did not answer the handshake."""


class MiioTokenError(MiioError):
    """No usable token is available (or the device rejected it)."""


@dataclass(frozen=True)
class Handshake:
    """Reply to the miIO hello packet."""

    host: str
    device_id: bytes
    stamp: int
    token_candidate: bytes
    raw: bytes

    @property
    def device_id_hex(self) -> str:
        return self.device_id.hex()

    @property
    def token_exposed(self) -> bool:
        return self.token_candidate not in (ZERO_TOKEN, EMPTY_TOKEN)

    @property
    def token_hex(self) -> str:
        return self.token_candidate.hex() if self.token_exposed else ""


def _token_key_iv(token: bytes) -> tuple[bytes, bytes]:
    key = hashlib.md5(token).digest()
    iv = hashlib.md5(key + token).digest()
    return key, iv


def encrypt_payload(plaintext: bytes, token: bytes) -> bytes:
    key, iv = _token_key_iv(token)
    return AES128(key).encrypt_cbc(plaintext, iv)


def decrypt_payload(ciphertext: bytes, token: bytes) -> bytes:
    key, iv = _token_key_iv(token)
    return AES128(key).decrypt_cbc(ciphertext, iv)


def build_packet(device_id: bytes, stamp: int, token: bytes, request: dict[str, Any]) -> bytes:
    """Frame and encrypt one miIO request."""
    if len(device_id) != 4:
        raise ValueError("device_id must be 4 bytes")
    if len(token) != 16:
        raise ValueError("token must be 16 bytes")
    plaintext = json.dumps(request, separators=(",", ":")).encode("utf-8") + b"\x00"
    encrypted = encrypt_payload(plaintext, token)
    total_length = 32 + len(encrypted)
    header = struct.pack(">HHIII", MAGIC, total_length, 0, int.from_bytes(device_id, "big"), stamp)
    checksum = hashlib.md5(header + token + encrypted).digest()
    return header + checksum + encrypted


def parse_packet(data: bytes, token: bytes) -> dict[str, Any]:
    """Validate and decrypt one miIO reply."""
    if len(data) < 32:
        raise MiioError(f"short miIO reply ({len(data)} bytes)")
    magic, length, _unknown, _device_id, _stamp = struct.unpack(">HHIII", data[:16])
    if magic != MAGIC:
        raise MiioError(f"unexpected miIO magic 0x{magic:04x}")
    if length and length > len(data):
        raise MiioError("truncated miIO reply")
    encrypted = data[32:length] if length else data[32:]
    checksum = data[16:32]
    expected = hashlib.md5(data[:16] + token + encrypted).digest()
    if checksum != expected:
        raise MiioTokenError("device rejected the token (checksum mismatch)")
    if not encrypted:
        raise MiioError("miIO reply has no payload")
    plaintext = decrypt_payload(encrypted, token)
    try:
        payload = json.loads(plaintext.rstrip(b"\x00").decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MiioError("could not decode miIO payload") from exc
    if not isinstance(payload, dict):
        raise MiioError("miIO payload is not an object")
    return payload


def handshake(
    host: str,
    port: int = MIIO_PORT,
    timeout: float = MIIO_TIMEOUT,
    retries: int = 2,
) -> Handshake:
    """Send the hello packet and parse the reply."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        last_error: Exception | None = None
        for _ in range(max(1, retries)):
            try:
                sock.sendto(HELLO_PACKET, (host, int(port)))
                data, _address = sock.recvfrom(1024)
            except (socket.timeout, TimeoutError) as exc:
                last_error = exc
                continue
            except OSError as exc:
                raise MiioUnavailable(f"cannot send to {host}:{port}: {exc}") from exc
            if len(data) < 32:
                last_error = MiioError(f"short hello reply ({len(data)} bytes)")
                continue
            magic = struct.unpack(">H", data[:2])[0]
            if magic != MAGIC:
                last_error = MiioError(f"unexpected magic 0x{magic:04x}")
                continue
            _magic, _length, _unknown, device_id, stamp = struct.unpack(">HHIII", data[:16])
            return Handshake(
                host=host,
                device_id=device_id.to_bytes(4, "big"),
                stamp=stamp,
                token_candidate=data[16:32],
                raw=data,
            )
        detail = f": {last_error}" if last_error else ""
        raise MiioUnavailable(
            f"{host}:{port} did not answer the miIO handshake{detail}. "
            "The firmware may not expose miIO, or UDP is blocked."
        )
    finally:
        sock.close()


class MiioClient:
    """Minimal UDP client for the miIO control protocol."""

    def __init__(
        self,
        host: str,
        token: bytes | str | None = None,
        port: int = MIIO_PORT,
        timeout: float = MIIO_TIMEOUT,
    ):
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)
        self.token = _normalise_token(token)
        self.device_id = b""
        self.stamp = 0
        self._id = 0
        self._sock: socket.socket | None = None

    def connect(self) -> "MiioClient":
        if self._sock is not None:
            return self
        info = handshake(self.host, self.port, self.timeout)
        self.device_id = info.device_id
        self.stamp = info.stamp
        if self.token is None and info.token_exposed:
            self.token = info.token_candidate
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.settimeout(self.timeout)
        return self

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None

    def __enter__(self) -> "MiioClient":
        return self.connect()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def send(self, method: str, params: Any = None) -> Any:
        self.connect()
        if self.token is None:
            raise MiioTokenError(
                "no token available. This firmware does not leak it during the "
                "handshake; pass --token with a token extracted from your own device."
            )
        if self._sock is None:
            raise MiioError("not connected")
        self._id = self._id % 9999 + 1
        if isinstance(params, dict):
            req_params: Any = params
        elif params is None:
            req_params = []
        else:
            req_params = list(params)
        request = {"id": self._id, "method": method, "params": req_params}
        self.stamp = (self.stamp + 1) & 0xFFFFFFFF
        packet = build_packet(self.device_id, self.stamp, self.token, request)
        try:
            self._sock.sendto(packet, (self.host, self.port))
            data, _address = self._sock.recvfrom(4096)
        except (socket.timeout, TimeoutError) as exc:
            raise MiioTokenError(
                "no reply from the device. This usually means the token is wrong, "
                "or the device does not accept miIO commands."
            ) from exc
        except OSError as exc:
            raise MiioError(f"miIO transport error: {exc}") from exc
        payload = parse_packet(data, self.token)
        if "error" in payload:
            error = payload.get("error") or {}
            raise MiioError(f"device error {error.get('code')}: {error.get('message')}")
        return payload.get("result", payload)


def _normalise_token(token: bytes | str | None) -> bytes | None:
    if token is None:
        return None
    if isinstance(token, str):
        text = token.strip().lower().replace("0x", "")
        if len(text) != 32:
            raise MiioTokenError("token must be 32 hexadecimal characters")
        try:
            token = bytes.fromhex(text)
        except ValueError as exc:
            raise MiioTokenError("token must be hexadecimal") from exc
    if len(token) != 16:
        raise MiioTokenError("token must be 16 bytes")
    return token


def probe(host: str, port: int = MIIO_PORT, timeout: float = MIIO_TIMEOUT) -> dict[str, Any]:
    """Read-only miIO check: handshake and report whether a token is exposed."""
    try:
        info = handshake(host, port, timeout)
    except MiioError as exc:
        return {"available": False, "host": host, "error": str(exc)}
    return {
        "available": True,
        "host": host,
        "port": port,
        "device_id": info.device_id_hex,
        "stamp": info.stamp,
        "token_exposed": info.token_exposed,
        "token": info.token_hex or None,
    }


def enable_lan_control(
    host: str,
    token: bytes | str | None = None,
    port: int = MIIO_PORT,
    control_port: int = CONTROL_PORT,
    timeout: float = MIIO_TIMEOUT,
    verify_seconds: float = 3.0,
) -> dict[str, Any]:
    """Ask the firmware to turn LAN Control on, then verify TCP 55443.

    Raises :class:`MiioTokenError` when no token is available. A device that
    answers with an error is reported instead of silently pretending success.
    """
    report: dict[str, Any] = {"host": host, "steps": []}
    info = handshake(host, port, timeout)
    report["device_id"] = info.device_id_hex
    report["token_exposed"] = info.token_exposed
    report["steps"].append("handshake")

    chosen = _normalise_token(token) or (info.token_candidate if info.token_exposed else None)
    if chosen is None:
        raise MiioTokenError(
            "this firmware does not expose its token during the handshake. "
            "LAN Control cannot be enabled over miIO without a token; use the "
            "official app once or the hardware path (docs/TANPA-LOGIN.md)."
        )
    report["token"] = chosen.hex()

    client = MiioClient(host, chosen, port, timeout)
    try:
        result = client.send("set_ps", ["cfg_lan_ctrl", "1"])
    finally:
        client.close()
    report["result"] = result
    report["steps"].append("set_ps")

    deadline = time.monotonic() + max(0.0, verify_seconds)
    open_port = False
    reason = "not checked"
    while True:
        open_port, reason = probe_port(host, control_port, timeout=min(1.0, timeout))
        if open_port or time.monotonic() >= deadline:
            break
        time.sleep(0.4)
    report["lan_control"] = open_port
    report["control_port"] = control_port
    report["detail"] = reason
    report["steps"].append("verify")
    return report


def provision_wifi(
    host: str = "192.168.10.1",
    ssid: str = "",
    password: str = "",
    token: bytes | str | None = None,
    port: int = MIIO_PORT,
    timeout: float = MIIO_TIMEOUT,
    enable_lan: bool = True,
    uid: int = 0,
) -> dict[str, Any]:
    """Provision Wi-Fi credentials to a bulb in AP mode (192.168.10.1).

    Optionally sets cfg_lan_ctrl=1 before sending miIO.config_router so that
    LAN Control is immediately active when the bulb joins the router network.
    """
    if not ssid:
        raise ValueError("ssid is required")
    report: dict[str, Any] = {"host": host, "ssid": ssid, "steps": []}
    info = handshake(host, port, timeout)
    report["device_id"] = info.device_id_hex
    report["token_exposed"] = info.token_exposed
    report["steps"].append("handshake")

    chosen = _normalise_token(token) or (info.token_candidate if info.token_exposed else None)
    if chosen is None:
        raise MiioTokenError("no token available for provisioning")
    report["token"] = chosen.hex()

    client = MiioClient(host, chosen, port, timeout)
    try:
        if enable_lan:
            try:
                lan_res = client.send("set_ps", ["cfg_lan_ctrl", "1"])
                report["lan_control_result"] = lan_res
                report["steps"].append("set_ps")
            except Exception as exc:
                report["lan_control_warning"] = str(exc)

        params = {
            "ssid": ssid,
            "passwd": password,
            "uid": uid,
        }
        res = client.send("miIO.config_router", params)
        report["result"] = res
        report["steps"].append("config_router")
    finally:
        client.close()
    return report

