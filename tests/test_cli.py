"""Parser-level tests: no network, no GUI window."""

from __future__ import annotations

import unittest

from yeelight_re import cli
from yeelight_re.cli import build_parser


class CliParserTests(unittest.TestCase):
    def test_every_subcommand_has_a_handler(self) -> None:
        parser = build_parser()
        actions = [
            action
            for action in parser._actions  # noqa: SLF001 - argparse has no public API
            if getattr(action, "choices", None) and isinstance(action.choices, dict)
        ]
        self.assertTrue(actions)
        for action in actions:
            for name, sub in action.choices.items():
                with self.subTest(command=name):
                    self.assertTrue(hasattr(sub.get_default("func"), "__call__"))

    def test_miio_exposes_timeout(self) -> None:
        # Regression: cmd_miio reads args.timeout, which must exist on both
        # the `miio` and `wifi-setup` parsers.
        args = build_parser().parse_args(["miio", "--ip", "192.168.1.20"])
        self.assertAlmostEqual(args.timeout, 3.0)
        args = build_parser().parse_args(
            ["wifi-setup", "--ssid", "Home", "--password", "secret"]
        )
        self.assertAlmostEqual(args.timeout, 3.0)

    def test_gui_arguments(self) -> None:
        args = build_parser().parse_args(["gui", "--ip", "192.168.1.20", "--port", "5555"])
        self.assertEqual(args.ip, "192.168.1.20")
        self.assertEqual(args.port, 5555)
        self.assertIs(args.func, cli.cmd_gui)

    def test_scan_options(self) -> None:
        args = build_parser().parse_args(["scan"])
        self.assertIsNone(args.subnet)
        self.assertAlmostEqual(args.connect_timeout, 0.25)
        self.assertAlmostEqual(args.identify_timeout, 2.0)
        self.assertIs(args.func, cli.cmd_scan)
        args = build_parser().parse_args(
            ["scan", "--subnet", "10.0.0.0/24", "--workers", "32"]
        )
        self.assertEqual(args.subnet, "10.0.0.0/24")
        self.assertEqual(args.workers, 32)

    def test_discover_scan_flag(self) -> None:
        args = build_parser().parse_args(["discover", "--scan"])
        self.assertTrue(args.scan)
        self.assertIs(args.func, cli.cmd_discover)

    def test_version_is_exported(self) -> None:
        from yeelight_re import __version__

        self.assertEqual(cli.VERSION, __version__)


if __name__ == "__main__":
    unittest.main()
