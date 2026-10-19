from __future__ import annotations

import unittest
from unittest import mock

from yeelight_re.client import MusicMode, YeelightClient
from yeelight_re.discovery import discover, probe_port
from yeelight_re.fake_bulb import FakeBulb
from yeelight_re.protocol import CommandError, LanControlDisabled


class ClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bulb = FakeBulb().start()
        self.client = YeelightClient("127.0.0.1", self.bulb.port, timeout=2.0).connect()

    def tearDown(self) -> None:
        self.client.close()
        self.bulb.stop()

    def test_get_props_and_status(self) -> None:
        status = self.client.status()
        self.assertEqual(status["power"], "on")
        self.assertEqual(status["bright"], 100)
        self.assertEqual(status["model"] if "model" in status else "color2", "color2")
        self.assertEqual(status["name"], "Fake YLDP06YL")

    def test_power_bright_rgb(self) -> None:
        self.assertEqual(self.client.set_power(False), ["ok"])
        self.assertEqual(self.client.status()["power"], "off")
        self.client.toggle()
        self.assertEqual(self.client.status()["power"], "on")
        self.client.set_bright(42)
        self.assertEqual(self.client.status()["bright"], 42)
        self.client.set_rgb(0xFF0080)
        status = self.client.status()
        self.assertEqual(status["rgb"], 0xFF0080)
        self.assertEqual(status["color_mode"], 2)
        self.client.set_ct(3200)
        self.assertEqual(self.client.status()["ct"], 3200)

    def test_hsv_and_scene(self) -> None:
        self.client.set_hsv(120, 100)
        status = self.client.status()
        self.assertEqual(status["color_mode"], 3)
        self.assertEqual(status["rgb"], 0x00FF00)
        self.client.set_scene("ct", 2700, 35)
        status = self.client.status()
        self.assertEqual(status["ct"], 2700)
        self.assertEqual(status["bright"], 35)
        self.assertEqual(status["color_mode"], 1)

    def test_notification(self) -> None:
        self.client.set_bright(55)
        props = self.client.get_notification(timeout=2.0)
        self.assertIsNotNone(props)
        assert props is not None
        self.assertEqual(props.get("bright"), "55")

    def test_error_is_raised(self) -> None:
        with self.assertRaises(CommandError) as context:
            self.client.send("definitely_not_a_method")
        self.assertEqual(context.exception.code, -4)

    def test_music_mode(self) -> None:
        with MusicMode(self.client) as music:
            self.assertGreater(music.port, 0)
            self.client.set_rgb(0x123456)
            props = music.get(timeout=2.0)
            for _ in range(3):
                if props and props.get("rgb") == str(0x123456):
                    break
                props = music.get(timeout=1.0)
            self.assertIsNotNone(props)
            assert props is not None
            self.assertEqual(props.get("rgb"), str(0x123456))
        self.assertEqual(self.client.status()["music_on"], 0)

    def test_connection_refused_is_explained(self) -> None:
        with mock.patch("socket.create_connection", side_effect=ConnectionRefusedError):
            with self.assertRaises(LanControlDisabled) as context:
                YeelightClient("127.0.0.1", 55443, timeout=0.5).connect()
        self.assertIn("LAN Control", str(context.exception))

    def test_probe_port(self) -> None:
        open_port, _ = probe_port("127.0.0.1", self.bulb.port, timeout=0.5)
        self.assertTrue(open_port)
        closed_port, reason = probe_port("127.0.0.1", 1, timeout=0.5)
        self.assertFalse(closed_port)
        self.assertTrue("refused" in reason.lower() or "timed out" in reason.lower())


class DiscoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bulb = FakeBulb().start()
        self.ssdp = self.bulb.enable_ssdp()

    def tearDown(self) -> None:
        self.bulb.stop()

    def test_discover(self) -> None:
        devices = discover(
            timeout=1.0,
            targets=[("127.0.0.1", self.ssdp.port)],
            retries=1,
        )
        self.assertEqual(len(devices), 1)
        device = devices[0]
        self.assertEqual(device.model, "color2")
        self.assertEqual(device.ip, "127.0.0.1")
        self.assertEqual(device.port, self.bulb.port)
        self.assertIn("set_rgb", device.support)


if __name__ == "__main__":
    unittest.main()
