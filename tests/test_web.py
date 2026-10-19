from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request

from yeelight_re.client import YeelightClient
from yeelight_re.fake_bulb import FakeBulb
from yeelight_re.web import make_server


class WebTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bulb = FakeBulb().start()
        self.client = YeelightClient("127.0.0.1", self.bulb.port, timeout=2.0).connect()
        self.server = make_server(self.client, "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)
        self.client.close()
        self.bulb.stop()

    def get_json(self, path: str) -> dict:
        with urllib.request.urlopen(self.base + path, timeout=3.0) as response:
            return json.loads(response.read().decode("utf-8"))

    def post_json(self, path: str, payload: dict) -> dict:
        request = urllib.request.Request(
            self.base + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=3.0) as response:
            return json.loads(response.read().decode("utf-8"))

    def test_index(self) -> None:
        with urllib.request.urlopen(self.base + "/", timeout=3.0) as response:
            body = response.read().decode("utf-8")
        self.assertIn("Yeelight Local", body)
        self.assertIn("/api/cmd", body)

    def test_state_and_command(self) -> None:
        state = self.get_json("/api/state")
        self.assertTrue(state["ok"])
        self.assertEqual(state["power"], "on")

        result = self.post_json("/api/cmd", {"method": "set_bright", "params": [33, "smooth", 0]})
        self.assertTrue(result["ok"])
        self.assertEqual(self.get_json("/api/state")["bright"], 33)

    def test_presets(self) -> None:
        presets = self.get_json("/api/presets")
        self.assertIn("relax", presets["scenes"])
        self.assertIn("party", presets["flows"])

    def test_disallowed_method(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as context:
            self.post_json("/api/cmd", {"method": "set_music", "params": [1, "x", 1]})
        self.assertEqual(context.exception.code, 400)
        context.exception.close()


if __name__ == "__main__":
    unittest.main()
