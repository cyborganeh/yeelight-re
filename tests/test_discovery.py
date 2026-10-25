from __future__ import annotations

import socket
import threading
import unittest

from yeelight_re.discovery import (
    BulbHit,
    identify,
    local_ipv4s,
    local_subnets,
    scan_lan,
)
from yeelight_re.fake_bulb import FakeBulb


class _PlainServer:
    """A TCP listener that is *not* a Yeelight endpoint."""

    def __init__(self) -> None:
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(8)
        self._sock.settimeout(0.3)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    @property
    def port(self) -> int:
        return int(self._sock.getsockname()[1])

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except (socket.timeout, OSError):
                continue
            conn.close()

    def __enter__(self) -> "_PlainServer":
        self._thread.start()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)
        self._sock.close()


class ScanLanTests(unittest.TestCase):
    def test_identify_reads_a_real_bulb(self) -> None:
        bulb = FakeBulb(name="Kamar").start()
        try:
            hit = identify("127.0.0.1", bulb.port, timeout=2.0)
        finally:
            bulb.stop()
        self.assertTrue(hit.is_bulb)
        self.assertEqual(hit.name, "Kamar")
        self.assertEqual(hit.model, "color2")
        self.assertEqual(hit.power, "on")
        self.assertEqual(hit.bright, 100)
        self.assertEqual(hit.error, "")

    def test_identify_rejects_a_plain_tcp_server(self) -> None:
        with _PlainServer() as server:
            hit = identify("127.0.0.1", server.port, timeout=0.5)
        self.assertFalse(hit.is_bulb)
        self.assertTrue(hit.error)

    def test_scan_lan_finds_and_identifies_the_bulb(self) -> None:
        bulb = FakeBulb().start()
        progress: list[tuple[int, int]] = []
        try:
            hits = scan_lan(
                "127.0.0.1/32",
                port=bulb.port,
                timeout=0.5,
                identify_timeout=2.0,
                on_progress=lambda done, total: progress.append((done, total)),
            )
        finally:
            bulb.stop()

        self.assertEqual(len(hits), 1)
        hit = hits[0]
        self.assertEqual(hit.ip, "127.0.0.1")
        self.assertTrue(hit.is_bulb)
        self.assertIn("Fake YLDP06YL", hit.label)
        self.assertEqual(progress[-1], (1, 1))

    def test_scan_lan_returns_empty_for_a_closed_port(self) -> None:
        probes: list[tuple[int, int]] = []
        hits = scan_lan(
            "127.0.0.1/32",
            port=1,
            timeout=0.2,
            identify_timeout=0.2,
            on_progress=lambda done, total: probes.append((done, total)),
        )
        self.assertEqual(hits, [])
        self.assertEqual(probes, [(0, 0)])

    def test_scan_lan_accepts_a_list_of_subnets(self) -> None:
        bulb = FakeBulb().start()
        try:
            hits = scan_lan(
                ["127.0.0.1/32", "127.0.0.1/32"],
                port=bulb.port,
                timeout=0.5,
                identify_timeout=2.0,
            )
        finally:
            bulb.stop()
        # The duplicate subnet is collapsed, so the bulb is only seen once.
        self.assertEqual([hit.ip for hit in hits], ["127.0.0.1"])

    def test_rejects_a_subnet_that_is_too_large(self) -> None:
        with self.assertRaises(ValueError):
            scan_lan("10.0.0.0/8", port=1, timeout=0.1)

    def test_local_subnets_skips_loopback_and_cgnat(self) -> None:
        subnets = [str(network) for network in local_subnets()]
        for network in subnets:
            self.assertFalse(network.startswith("127."), network)
            self.assertFalse(network.startswith("100.64."), network)
            self.assertFalse(network.startswith("169.254."), network)
        self.assertEqual(len(subnets), len(set(subnets)))

    def test_local_ipv4s_is_unique(self) -> None:
        addresses = local_ipv4s()
        self.assertEqual(len(addresses), len(set(addresses)))
        for address in addresses:
            self.assertFalse(address.startswith("127."), address)

    def test_hit_label_and_dict(self) -> None:
        hit = BulbHit(
            ip="192.168.1.30",
            is_bulb=True,
            name="Teras",
            model="color2",
            power="off",
            bright=35,
        )
        self.assertIn("Teras", hit.label)
        self.assertIn("mati", hit.label)
        self.assertIn("35%", hit.label)
        payload = hit.as_dict()
        self.assertTrue(payload["is_bulb"])
        self.assertEqual(payload["ip"], "192.168.1.30")

        stranger = BulbHit(ip="192.168.1.99", error="timed out")
        self.assertIn("bukan Yeelight", stranger.label)
        self.assertFalse(stranger.as_dict()["is_bulb"])


if __name__ == "__main__":
    unittest.main()
