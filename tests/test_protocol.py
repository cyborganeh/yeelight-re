from __future__ import annotations

import unittest

from yeelight_re.protocol import (
    M_SEARCH,
    ProtocolError,
    build_flow,
    format_command,
    parse_message,
    parse_rgb,
    parse_ssdp,
    rgb_components,
    rgb_from_hsv,
    rgb_to_hex,
)


SSDP_SAMPLE = (
    "HTTP/1.1 200 OK\r\n"
    "Cache-Control: max-age=3600\r\n"
    "Location: yeelight://192.168.1.50:55443\r\n"
    "Server: POSIX UPnP/1.0 YGLC/1\r\n"
    "id: 0x0000000012345678\r\n"
    "model: color2\r\n"
    "fw_ver: 18\r\n"
    "support: get_prop set_power toggle set_bright set_rgb set_music\r\n"
    "power: on\r\n"
    "bright: 73\r\n"
    "color_mode: 2\r\n"
    "ct: 4000\r\n"
    "rgb: 16711680\r\n"
    "hue: 0\r\n"
    "sat: 100\r\n"
    "name: Living Room\r\n"
    "\r\n"
)


class ProtocolTests(unittest.TestCase):
    def test_m_search(self) -> None:
        self.assertIn(b"ST: wifi_bulb", M_SEARCH)
        self.assertTrue(M_SEARCH.endswith(b"\r\n\r\n"))

    def test_parse_ssdp(self) -> None:
        device = parse_ssdp(SSDP_SAMPLE)
        self.assertIsNotNone(device)
        assert device is not None
        self.assertEqual(device.ip, "192.168.1.50")
        self.assertEqual(device.port, 55443)
        self.assertEqual(device.model, "color2")
        self.assertEqual(device.fw_ver, "18")
        self.assertEqual(device.bright, 73)
        self.assertEqual(device.rgb, 16711680)
        self.assertEqual(device.name, "Living Room")
        self.assertIn("set_rgb", device.support)
        self.assertTrue(device.is_color)
        self.assertEqual(device.location, "yeelight://192.168.1.50:55443")

    def test_parse_ssdp_rejects_non_200(self) -> None:
        self.assertIsNone(parse_ssdp("HTTP/1.1 404 Not Found\r\n\r\n"))

    def test_format_command(self) -> None:
        payload = format_command(7, "set_power", ["on", "smooth", 300])
        self.assertTrue(payload.endswith(b"\r\n"))
        self.assertEqual(
            payload,
            b'{"id":7,"method":"set_power","params":["on","smooth",300]}\r\n',
        )

    def test_parse_message(self) -> None:
        self.assertEqual(parse_message('{"id":1,"result":["ok"]}')["id"], 1)
        with self.assertRaises(ProtocolError):
            parse_message("not json")
        with self.assertRaises(ProtocolError):
            parse_message("[]")

    def test_parse_rgb(self) -> None:
        self.assertEqual(parse_rgb("#ff0000"), 0xFF0000)
        self.assertEqual(parse_rgb("0xff0000"), 0xFF0000)
        self.assertEqual(parse_rgb("255,0,128"), 0xFF0080)
        self.assertEqual(parse_rgb(0x00FF00), 0x00FF00)
        with self.assertRaises(ValueError):
            parse_rgb("300,0,0")
        with self.assertRaises(ValueError):
            parse_rgb("0x1000000")

    def test_rgb_helpers(self) -> None:
        self.assertEqual(rgb_to_hex(0x0A0B0C), "#0a0b0c")
        self.assertEqual(rgb_components(0x0A0B0C), (10, 11, 12))
        self.assertEqual(rgb_from_hsv(0, 100), 0xFF0000)
        self.assertEqual(rgb_from_hsv(120, 100), 0x00FF00)
        self.assertEqual(rgb_from_hsv(240, 100), 0x0000FF)

    def test_build_flow(self) -> None:
        self.assertEqual(
            build_flow([(500, 1, 0xFF0000, 100), (1000, 2, 2700, 40)]),
            "500,1,16711680,100,1000,2,2700,40",
        )
        with self.assertRaises(ValueError):
            build_flow([(10, 1, 0, 100)])
        with self.assertRaises(ValueError):
            build_flow([(500, 2, 7000, 100)])
        with self.assertRaises(ValueError):
            build_flow([])


if __name__ == "__main__":
    unittest.main()
