"""Discovery helpers: SSDP multicast and a small TCP port scanner."""

from __future__ import annotations

import ipaddress
import select
import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Iterable, Sequence

from .protocol import (
    CONTROL_PORT,
    M_SEARCH,
    SSDP_ADDRESS,
    SSDP_PORT,
    Device,
    parse_ssdp,
)


def local_ipv4() -> str | None:
    """Best-effort local IPv4 address (does not send any packets)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("1.1.1.1", 80))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def discover(
    timeout: float = 3.0,
    targets: Sequence[tuple[str, int]] | None = None,
    retries: int = 3,
) -> list[Device]:
    """Discover LAN-mode Yeelight devices.

    Sends the documented ``M-SEARCH`` to the Yeelight multicast group and to the
    limited broadcast address, then collects unicast replies. ``targets`` exists
    mainly for tests; leave it as ``None`` in normal use.
    """
    if targets is None:
        targets = [(SSDP_ADDRESS, SSDP_PORT), ("255.255.255.255", SSDP_PORT)]

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    try:
        sock.bind(("", 0))
    except OSError:
        sock.close()
        raise
    sock.setblocking(False)

    devices: dict[str, Device] = {}
    deadline = time.monotonic() + max(0.2, timeout)
    next_send = 0.0
    sends_left = max(1, retries)

    try:
        while time.monotonic() < deadline:
            now = time.monotonic()
            if sends_left > 0 and now >= next_send:
                for target in targets:
                    try:
                        sock.sendto(M_SEARCH, target)
                    except OSError:
                        pass
                sends_left -= 1
                next_send = now + min(0.4, max(0.1, timeout / (retries + 1)))

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            readable, _, _ = select.select([sock], [], [], min(0.2, remaining))
            if not readable:
                continue
            while True:
                try:
                    payload, address = sock.recvfrom(65535)
                except (BlockingIOError, ConnectionResetError):
                    break
                device = parse_ssdp(payload, address)
                if device is None:
                    continue
                key = device.id or f"{device.ip}:{device.port}"
                devices[key] = device
    finally:
        sock.close()

    return sorted(devices.values(), key=lambda item: ipaddress.ip_address(item.ip))


def _default_subnet() -> ipaddress.IPv4Network:
    address = local_ipv4()
    if not address:
        raise RuntimeError("could not determine the local IPv4 network; pass --subnet")
    return ipaddress.ip_network(f"{address}/24", strict=False)


def scan_subnet(
    subnet: str | ipaddress.IPv4Network | None = None,
    port: int = CONTROL_PORT,
    timeout: float = 0.25,
    workers: int = 128,
) -> list[str]:
    """Return IPs in ``subnet`` that accept TCP connections on ``port``.

    This only finds bulbs that already have LAN Control enabled; it cannot wake
    up a bulb whose port 55443 is closed.
    """
    network = ipaddress.ip_network(subnet, strict=False) if subnet else _default_subnet()
    if network.version != 4:
        raise ValueError("only IPv4 subnets are supported")
    if network.num_addresses > 4096:
        raise ValueError("subnet is too large; use a /20 or smaller range")

    hosts = [str(host) for host in network.hosts()]
    if not hosts:
        return []

    def probe(address: str) -> bool:
        try:
            with socket.create_connection((address, port), timeout=timeout):
                return True
        except OSError:
            return False

    found: list[str] = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(hosts)))) as pool:
        futures = {pool.submit(probe, host): host for host in hosts}
        for future in as_completed(futures):
            if future.result():
                found.append(futures[future])
    return sorted(found, key=ipaddress.ip_address)


def probe_port(host: str, port: int = CONTROL_PORT, timeout: float = 2.0) -> tuple[bool, str]:
    """Check whether a TCP port is open and return a human-readable reason."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, "open"
    except ConnectionRefusedError:
        return False, "connection refused (LAN Control / Developer Mode is probably off)"
    except TimeoutError:
        return False, "timed out (wrong IP, different VLAN, or firewall)"
    except OSError as exc:
        return False, str(exc)


def format_device(device: Device, index: int | None = None) -> str:
    prefix = f"[{index}] " if index is not None else ""
    name = device.name or "(no name)"
    return (
        f"{prefix}{device.ip}:{device.port}  {device.model or '?'}  "
        f"fw {device.fw_ver or '?'}  {name}"
    )


def unique_by_ip(devices: Iterable[Device]) -> list[Device]:
    seen: dict[str, Device] = {}
    for device in devices:
        seen.setdefault(device.ip, device)
    return sorted(seen.values(), key=lambda item: ipaddress.ip_address(item.ip))
