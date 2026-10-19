"""Colour scenes and flow presets shared by the CLI and the web UI."""

from __future__ import annotations

from typing import Any

from .protocol import build_flow

#: name -> set_scene parameters
SCENES: dict[str, tuple[Any, ...]] = {
    "reading": ("ct", 4000, 100),
    "relax": ("ct", 2700, 40),
    "night": ("ct", 1900, 5),
    "focus": ("ct", 5000, 100),
    "movie": ("color", 0x1414FF, 15),
    "sunset": ("color", 0xFF5A1F, 40),
    "forest": ("color", 0x1F7A3D, 45),
    "ocean": ("color", 0x0066CC, 45),
    "candle": ("color", 0xFF9329, 30),
}

#: name -> (count, action, flow expression)
FLOW_PRESETS: dict[str, tuple[int, int, str]] = {
    "party": (
        0,
        1,
        build_flow(
            [
                (700, 1, 0xFF0000, 100),
                (700, 1, 0x00FF00, 100),
                (700, 1, 0x0000FF, 100),
                (700, 1, 0xFFFF00, 100),
                (700, 1, 0xFF00FF, 100),
                (700, 1, 0x00FFFF, 100),
            ]
        ),
    ),
    "rainbow": (
        0,
        1,
        build_flow(
            [
                (500, 1, 0xFF0000, 100),
                (500, 1, 0xFF7F00, 100),
                (500, 1, 0xFFFF00, 100),
                (500, 1, 0x00FF00, 100),
                (500, 1, 0x0000FF, 100),
                (500, 1, 0x4B0082, 100),
                (500, 1, 0x9400D3, 100),
            ]
        ),
    ),
    "sunrise": (
        1,
        1,
        build_flow([(120000, 2, 2700, 1), (120000, 2, 4000, 100)]),
    ),
    "sunset": (
        1,
        1,
        build_flow([(120000, 2, 2700, 100), (120000, 2, 2700, 1)]),
    ),
    "candle": (
        0,
        1,
        build_flow(
            [
                (250, 2, 2200, 35),
                (350, 2, 2400, 55),
                (180, 2, 2100, 25),
                (420, 2, 2500, 65),
                (260, 2, 2300, 40),
            ]
        ),
    ),
}


def scene_params(name: str) -> tuple[Any, ...]:
    try:
        return SCENES[name]
    except KeyError as exc:
        raise ValueError(f"unknown scene '{name}'; choose from {', '.join(sorted(SCENES))}") from exc


def flow_params(name: str) -> tuple[int, int, str]:
    try:
        return FLOW_PRESETS[name]
    except KeyError as exc:
        raise ValueError(
            f"unknown flow preset '{name}'; choose from {', '.join(sorted(FLOW_PRESETS))}"
        ) from exc
