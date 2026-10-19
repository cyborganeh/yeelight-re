from __future__ import annotations

import unittest

from yeelight_re._aes import AES128
from yeelight_re.fake_bulb import FakeBulb, FakeMiio
from yeelight_re.miio import (
    MiioClient,
    MiioTokenError,
    build_packet,
    enable_lan_control,
    handshake,
    parse_packet,
    probe,
    provision_wifi,
)


class AesTests(unittest.TestCase):
    def test_fips_197_vector(self) -> None:
        key = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
        plaintext = bytes.fromhex("00112233445566778899aabbccddeeff")
        expected = bytes.fromhex("69c4e0d86a7b0430d8cdb78070b4c55a")
        cipher = AES128(key)
        self.assertEqual(cipher.encrypt_block(plaintext), expected)
        self.assertEqual(cipher.decrypt_block(expected), plaintext)

    def test_cbc_roundtrip_and_padding(self) -> None:
        cipher = AES128(bytes(range(16)))
        iv = bytes(range(16, 32))
        for message in (b"", b"a", b"x" * 16, b"hello miio" * 7):
            encrypted = cipher.encrypt_cbc(message, iv)
            self.assertEqual(len(encrypted) % 16, 0)
            self.assertEqual(cipher.decrypt_cbc(encrypted, iv), message)


class MiioTests(unittest.TestCase):
    def setUp(self) -> None:
        self.miio = FakeMiio().start()

    def tearDown(self) -> None:
        self.miio.stop()

    def test_handshake_exposes_token(self) -> None:
        info = handshake("127.0.0.1", self.miio.port, timeout=1.0)
        self.assertEqual(info.device_id, (0x12345678).to_bytes(4, "big"))
        self.assertTrue(info.token_exposed)
        self.assertEqual(info.token_candidate, self.miio.token)

    def test_handshake_can_hide_token(self) -> None:
        hidden = FakeMiio(expose_token=False).start()
        try:
            info = handshake("127.0.0.1", hidden.port, timeout=1.0)
            self.assertFalse(info.token_exposed)
            probe_result = probe("127.0.0.1", hidden.port, timeout=1.0)
            self.assertFalse(probe_result["token_exposed"])
        finally:
            hidden.stop()

    def test_set_ps_enables_lan_flag(self) -> None:
        with MiioClient("127.0.0.1", port=self.miio.port, timeout=1.0) as client:
            result = client.send("set_ps", ["cfg_lan_ctrl", "1"])
        self.assertEqual(result, ["ok"])
        self.assertTrue(self.miio.lan_enabled)
        self.assertEqual(self.miio.requests[-1]["method"], "set_ps")

    def test_explicit_token(self) -> None:
        hidden = FakeMiio(expose_token=False).start()
        try:
            with MiioClient(
                "127.0.0.1", hidden.token, port=hidden.port, timeout=1.0
            ) as client:
                self.assertEqual(client.send("miio.info"), ["color2"])
            self.assertTrue(hidden.requests)
        finally:
            hidden.stop()

    def test_missing_token_is_explained(self) -> None:
        hidden = FakeMiio(expose_token=False).start()
        try:
            with self.assertRaises(MiioTokenError):
                with MiioClient("127.0.0.1", port=hidden.port, timeout=1.0) as client:
                    client.send("set_ps", ["cfg_lan_ctrl", "1"])
        finally:
            hidden.stop()

    def test_wrong_token_is_rejected(self) -> None:
        request = {"id": 1, "method": "miio.info", "params": []}
        packet = build_packet(
            (0x12345678).to_bytes(4, "big"), 1, bytes(16), request
        )
        with self.assertRaises(MiioTokenError):
            parse_packet(packet, bytes([1]) * 16)

    def test_enable_lan_control_verifies_tcp(self) -> None:
        bulb = FakeBulb().start()
        try:
            report = enable_lan_control(
                "127.0.0.1",
                port=self.miio.port,
                control_port=bulb.port,
                timeout=1.0,
                verify_seconds=0.0,
            )
            self.assertTrue(report["lan_control"])
            self.assertTrue(report["token_exposed"])
            self.assertEqual(report["result"], ["ok"])
            self.assertTrue(self.miio.lan_enabled)
        finally:
            bulb.stop()

    def test_enable_without_token_fails_cleanly(self) -> None:
        hidden = FakeMiio(expose_token=False).start()
        try:
            with self.assertRaises(MiioTokenError):
                enable_lan_control(
                    "127.0.0.1",
                    port=hidden.port,
                    control_port=1,
                    timeout=1.0,
                )
        finally:
            hidden.stop()

    def test_provision_wifi(self) -> None:
        report = provision_wifi(
            "127.0.0.1",
            ssid="TestWiFi",
            password="secretpassword",
            port=self.miio.port,
            timeout=1.0,
            enable_lan=True,
        )
        self.assertEqual(report["ssid"], "TestWiFi")
        self.assertEqual(report["result"], ["ok"])
        self.assertTrue(self.miio.lan_enabled)
        # Verify the router config was sent
        last_req = self.miio.requests[-1]
        self.assertEqual(last_req["method"], "miIO.config_router")
        self.assertEqual(last_req["params"]["ssid"], "TestWiFi")
        self.assertEqual(last_req["params"]["passwd"], "secretpassword")


if __name__ == "__main__":
    unittest.main()
