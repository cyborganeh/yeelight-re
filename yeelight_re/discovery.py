"""Discovery helpers: SSDP multicast, TCP port scanner and subnet scan.

SSDP is the cheapest way to find a bulb, but plenty of routers drop multicast,
and a bulb that changed its DHCP lease can only be found by walking the subnet.
:func:`scan_lan` covers that case: it probes TCP 55443 on every host and then
identifies the ones that answer with a real ``get_prop`` call.
"""

from __future__ import annotations

import ipaddress
import select
import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

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


def local_ipv4s() -> list[str]:
    """Every usable IPv4 address of this machine, best effort.

    A PC often has several interfaces (Wi-Fi, Ethernet, VPN, Hyper-V). The
    default route is not necessarily the one the bulb lives on, so the subnet
    scan looks at all of them.
    """
    found: list[str] = []

    def add(value: str | None) -> None:
        if not value:
            return
        try:
            address = ipaddress.IPv4Address(value)
        except ValueError:
            return
        if (
            address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_unspecified
        ):
            return
        if str(address) not in found:
            found.append(str(address))

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            add(str(info[4][0]))
    except OSError:
        pass
    add(local_ipv4())
    return found


def local_subnets(prefix: int = 24) -> list[ipaddress.IPv4Network]:
    """Local networks to scan, one per interface, without duplicates."""
    cgnat = ipaddress.ip_network("100.64.0.0/10")  # Tailscale / carrier NAT
    networks: list[ipaddress.IPv4Network] = []
    for address in local_ipv4s():
        try:
            network = ipaddress.ip_network(f"{address}/{prefix}", strict=False)
        except ValueError:
            continue
        if network.overlaps(cgnat):
            # A VPN tunnel never carries a Yeelight bulb.
            continue
        if network not in networks:
            networks.append(network)
    return networks


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


def _normalize_subnets(
    subnet: str | ipaddress.IPv4Network | Sequence[str | ipaddress.IPv4Network] | None,
) -> list[ipaddress.IPv4Network]:
    """Turn user input (single subnet, list, or ``None``) into networks."""
    if subnet is None or subnet == "":
        networks = local_subnets()
        if not networks:
            raise RuntimeError(
                "could not determine the local IPv4 network; pass --subnet"
            )
        return networks

    if isinstance(subnet, (str, ipaddress.IPv4Network)):
        raw: Sequence[str | ipaddress.IPv4Network] = [subnet]
    else:
        raw = list(subnet)

    networks = []
    for value in raw:
        network = ipaddress.ip_network(value, strict=False)
        if network.version != 4:
            raise ValueError("only IPv4 subnets are supported")
        if network.num_addresses > 4096:
            raise ValueError("subnet is too large; use a /20 or smaller range")
        if network not in networks:
            networks.append(network)
    return networks


def scan_subnet(
    subnet: str | ipaddress.IPv4Network | Sequence[str | ipaddress.IPv4Network] | None = None,
    port: int = CONTROL_PORT,
    timeout: float = 0.25,
    workers: int = 128,
) -> list[str]:
    """Return IPs that accept TCP connections on ``port``.

    With no ``subnet`` every local interface is scanned on its /24, because a
    PC with Wi-Fi, Ethernet and a VPN often has a default route that is not the
    network the bulb lives on.

    This only finds bulbs that already have LAN Control enabled; it cannot wake
    up a bulb whose port 55443 is closed.
    """
    networks = _normalize_subnets(subnet)
    hosts: list[str] = []
    for network in networks:
        for host in network.hosts():
            address = str(host)
            if address not in hosts:
                hosts.append(address)
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


@dataclass
class BulbHit:
    """One host that was found by :func:`scan_lan`.

    ``is_bulb`` is ``True`` only when the host answered a real Yeelight
    ``get_prop`` request. A host with the port open but no valid answer is kept
    as well, because that is useful when diagnosing firewalls.
    """

    ip: str
    port: int = CONTROL_PORT
    is_bulb: bool = False
    name: str = ""
    model: str = ""
    power: str = ""
    bright: int | None = None
    status: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ip": self.ip,
            "port": self.port,
            "is_bulb": self.is_bulb,
            "name": self.name,
            "model": self.model,
            "power": self.power,
            "bright": self.bright,
            "status": self.status,
            "error": self.error,
        }

    @property
    def label(self) -> str:
        if not self.is_bulb:
            return f"{self.ip}:{self.port} (port terbuka, bukan Yeelight)"
        name = self.name or "tanpa nama"
        bright = f"{self.bright}%" if isinstance(self.bright, int) else "?"
        power = {"on": "nyala", "off": "mati"}.get(self.power, self.power or "?")
        return f"{self.ip}:{self.port} | {name} | {power} | {bright}"


def identify(host: str, port: int = CONTROL_PORT, timeout: float = 2.0) -> BulbHit:
    """Ask one host whether it speaks the Yeelight LAN protocol."""
    from .client import YeelightClient  # local import: avoid a cycle at import time
    from .protocol import INT_PROPS, STATUS_PROPS

    try:
        with YeelightClient(host, port, timeout=timeout) as client:
            raw = client.get_props([*STATUS_PROPS, "model"])
    except Exception as exc:  # noqa: BLE001 - any failure means "not a bulb"
        return BulbHit(ip=host, port=port, error=str(exc))

    status: dict[str, Any] = {}
    for key, value in raw.items():
        if key in INT_PROPS:
            try:
                status[key] = int(value)
            except (TypeError, ValueError):
                status[key] = None
        else:
            status[key] = value

    bright = status.get("bright")
    return BulbHit(
        ip=host,
        port=port,
        is_bulb=True,
        name=str(status.get("name") or ""),
        model=str(status.get("model") or ""),
        power=str(status.get("power") or ""),
        bright=bright if isinstance(bright, int) else None,
        status=status,
    )


def scan_lan(
    subnet: str | ipaddress.IPv4Network | Sequence[str | ipaddress.IPv4Network] | None = None,
    port: int = CONTROL_PORT,
    timeout: float = 0.25,
    workers: int = 128,
    identify_timeout: float = 2.0,
    on_progress: Callable[[int, int], None] | None = None,
) -> list[BulbHit]:
    """Scan the local network and identify every Yeelight bulb on it.

    This is the recovery path when the bulb's DHCP address changes and SSDP
    does not answer: it walks the subnet for open TCP 55443 ports and then runs
    ``get_prop`` against each hit. Without ``subnet`` every local interface is
    scanned on its /24, which matters on laptops with Wi-Fi, Ethernet and VPN.

    Returns the confirmed bulbs first, then any other hosts with the port open.
    """
    open_hosts = scan_subnet(subnet, port=port, timeout=timeout, workers=workers)
    total = len(open_hosts)
    if on_progress is not None:
        on_progress(0, total)

    hits: list[BulbHit] = []
    if total == 0:
        return hits

    done = 0
    with ThreadPoolExecutor(max_workers=max(1, min(workers, total))) as pool:
        futures = {
            pool.submit(identify, host, port, identify_timeout): host for host in open_hosts
        }
        for future in as_completed(futures):
            hits.append(future.result())
            done += 1
            if on_progress is not None:
                on_progress(done, total)

    hits.sort(key=lambda hit: (not hit.is_bulb, ipaddress.ip_address(hit.ip)))
    return hits


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
