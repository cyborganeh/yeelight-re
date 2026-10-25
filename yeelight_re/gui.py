"""Desktop GUI for the local Yeelight toolkit.

Tkinter only: no third-party packages, so the same code runs from source and
inside the PyInstaller ``yeelight-re-gui.exe`` build.

The window is deliberately task-oriented:

* connect (with an automatic miIO unlock attempt when TCP 55443 is closed),
* control power, brightness, colour, HSV and colour temperature,
* scenes, flows, music mode and a delay-off timer,
* rename, raw commands, diagnostics and a live event log.
"""

from __future__ import annotations

import colorsys
import json
import math
import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, messagebox, simpledialog, ttk
from typing import Any, Callable

from .client import MusicMode, YeelightClient
from .discovery import discover, local_ipv4, probe_port, scan_lan, unique_by_ip
from .miio import (
    MIIO_PORT,
    MiioError,
    MiioTokenError,
    enable_lan_control,
    probe as miio_probe,
)
from .presets import FLOW_PRESETS, SCENES, flow_params
from .protocol import (
    CONTROL_PORT,
    INT_PROPS,
    LanControlDisabled,
    YeelightError,
    clamp,
    rgb_to_hex,
)

BG = "#0f131a"
PANEL = "#171c26"
PANEL2 = "#1e2431"
FIELD = "#0c1017"
FG = "#e9eef8"
MUTED = "#93a0b5"
ACCENT = "#ffbf3f"
GREEN = "#39d98a"
RED = "#ff6b7a"
BORDER = "#2a3242"

PRESET_COLOURS = (
    ("#ff3b30", 0xFF3B30),
    ("#ff9500", 0xFF9500),
    ("#ffcc00", 0xFFCC00),
    ("#34c759", 0x34C759),
    ("#00c7be", 0x00C7BE),
    ("#007aff", 0x007AFF),
    ("#5856d6", 0x5856D6),
    ("#af52de", 0xAF52DE),
    ("#ff2d55", 0xFF2D55),
    ("#ffffff", 0xFFFFFF),
)

SCENE_LABELS = {
    "reading": "Baca",
    "relax": "Santai",
    "night": "Malam",
    "focus": "Fokus",
    "movie": "Film",
    "sunset": "Senja",
    "forest": "Hutan",
    "ocean": "Laut",
    "candle": "Lilin",
}


def _resource(name: str) -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base) / name
    return Path(__file__).resolve().parent.parent / name


def _config_path() -> Path:
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return Path(base) / "yeelight-re" / "gui.json"


class YeelightGui(tk.Tk):
    def __init__(self, ip: str | None = None, port: int = CONTROL_PORT):
        super().__init__()
        saved = self._load_settings()
        self.title("yeelight-re — YLDP06YL")
        self.geometry("1060x760")
        self.minsize(940, 660)
        self.configure(bg=BG)

        icon = _resource("yeelight.ico")
        if icon.exists():
            try:
                self.iconbitmap(str(icon))
            except tk.TclError:
                pass

        self.client: YeelightClient | None = None
        self.devices: dict[str, Any] = {}
        self.state: dict[str, Any] = {}
        self.connected = False
        self._queue: queue.Queue[tuple[Callable[..., Any], tuple[Any, ...]]] = queue.Queue()
        self._syncing = False
        self._bright_job: str | None = None
        self._ct_job: str | None = None
        self._poll_job: str | None = None
        self._music_thread: threading.Thread | None = None
        self._music_stop = threading.Event()
        self._closing = False
        self._controls: list[tk.Widget] = []

        self.ip_var = tk.StringVar(value=ip or saved.get("ip", ""))
        self.port_var = tk.StringVar(value=str(port or saved.get("port", CONTROL_PORT)))
        self.subnet_var = tk.StringVar(value=str(saved.get("subnet", "")))
        self.status_var = tk.StringVar(value="Belum terhubung")
        self.bright_var = tk.DoubleVar(value=100)
        self.ct_var = tk.DoubleVar(value=4000)
        self.bright_label = tk.StringVar(value="100%")
        self.ct_label = tk.StringVar(value="4000 K")
        self.colour_label = tk.StringVar(value="#ffffff")
        self.hue_var = tk.StringVar(value="0")
        self.sat_var = tk.StringVar(value="0")
        self.scene_hint = tk.StringVar(value="Pilih suasana untuk langsung diterapkan.")
        self.flow_var = tk.StringVar(value="rainbow")
        self.flow_count_var = tk.StringVar(value="0")
        self.music_mode_var = tk.StringVar(value="rainbow")
        self.music_seconds_var = tk.StringVar(value="15")
        self.timer_var = tk.StringVar(value="30")
        self.token_var = tk.StringVar(value="")
        self.raw_method_var = tk.StringVar(value="get_prop")
        self.raw_params_var = tk.StringVar(value='["power", "bright"]')
        self.rename_var = tk.StringVar(value="")

        self._build_styles()
        self._build_layout()
        self._set_controls_enabled(False)
        self._set_status("Belum terhubung", MUTED)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(50, self._drain)
        self.log("Siap. Masukkan IP bulb atau klik Cari.", "muted")
        if self.ip_var.get().strip():
            # A saved IP may be stale (DHCP); the failed connect triggers a
            # subnet scan so the bulb is found again automatically.
            self.after(500, lambda: self.connect(fallback_scan=True))

    # ------------------------------------------------------------------ setup

    def _load_settings(self) -> dict[str, Any]:
        try:
            return json.loads(_config_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_settings(self) -> None:
        try:
            path = _config_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {
                        "ip": self.ip_var.get().strip(),
                        "port": self.port_var.get(),
                        "subnet": self.subnet_var.get().strip(),
                    }
                ),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _build_styles(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG, foreground=FG, font=("Segoe UI", 10))
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=FG)
        style.configure("Panel.TLabel", background=PANEL, foreground=FG)
        style.configure("PanelMuted.TLabel", background=PANEL, foreground=MUTED)
        style.configure(
            "Title.TLabel", background=BG, foreground=FG, font=("Segoe UI Semibold", 19)
        )
        style.configure("Sub.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 9))
        style.configure(
            "H1.TLabel",
            background=PANEL,
            foreground=FG,
            font=("Segoe UI Semibold", 11),
        )
        style.configure(
            "Value.TLabel",
            background=PANEL,
            foreground=ACCENT,
            font=("Segoe UI Semibold", 12),
        )
        style.configure(
            "TButton",
            background=PANEL2,
            foreground=FG,
            bordercolor=BORDER,
            borderwidth=0,
            focusthickness=0,
            padding=(12, 7),
        )
        style.map(
            "TButton",
            background=[("active", "#2c3547"), ("disabled", "#202632")],
            foreground=[("disabled", "#5c6678")],
        )
        style.configure(
            "Accent.TButton",
            background=ACCENT,
            foreground="#1a1405",
            font=("Segoe UI Semibold", 10),
            padding=(14, 7),
        )
        style.map(
            "Accent.TButton",
            background=[("active", "#ffd36b"), ("disabled", "#4b432c")],
            foreground=[("disabled", "#2a2518")],
        )
        style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(0, 6, 0, 0))
        style.configure(
            "TNotebook.Tab",
            background=PANEL,
            foreground=MUTED,
            padding=(18, 9),
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", PANEL2)],
            foreground=[("selected", ACCENT)],
        )
        style.configure(
            "TEntry",
            fieldbackground=FIELD,
            foreground=FG,
            insertcolor=FG,
            bordercolor=BORDER,
            lightcolor=BORDER,
            darkcolor=BORDER,
            padding=5,
        )
        style.map("TEntry", bordercolor=[("focus", ACCENT)])
        style.configure(
            "TCombobox",
            fieldbackground=FIELD,
            background=PANEL2,
            foreground=FG,
            arrowcolor=FG,
            bordercolor=BORDER,
            padding=4,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", FIELD)],
            foreground=[("readonly", FG)],
            bordercolor=[("focus", ACCENT)],
        )
        style.configure(
            "TSpinbox",
            fieldbackground=FIELD,
            foreground=FG,
            arrowcolor=FG,
            bordercolor=BORDER,
            padding=4,
        )
        style.configure(
            "TScale", background=PANEL, troughcolor=FIELD, borderwidth=0, lightcolor=ACCENT
        )
        style.map("TScale", background=[("active", PANEL)])
        style.configure("TCheckbutton", background=PANEL, foreground=FG)
        style.map("TCheckbutton", background=[("active", PANEL)])

    def _build_layout(self) -> None:
        outer = tk.Frame(self, bg=BG, padx=18, pady=14)
        outer.pack(fill="both", expand=True)
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(2, weight=1)

        header = tk.Frame(outer, bg=BG)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(1, weight=1)
        ttk.Label(header, text="yeelight-re", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(
            header,
            text="YLDP06YL · kontrol lokal, tanpa cloud",
            style="Sub.TLabel",
        ).grid(row=1, column=0, sticky="w")
        self.status_label = tk.Label(
            header,
            textvariable=self.status_var,
            bg=PANEL2,
            fg=MUTED,
            font=("Segoe UI Semibold", 10),
            padx=14,
            pady=7,
        )
        self.status_label.grid(row=0, column=2, rowspan=2, sticky="e")

        connection = tk.Frame(
            outer, bg=PANEL, highlightbackground=BORDER, highlightthickness=1
        )
        connection.grid(row=1, column=0, sticky="ew", pady=(12, 12))
        row = tk.Frame(connection, bg=PANEL, padx=14, pady=11)
        row.pack(fill="x")
        ttk.Label(row, text="IP bulb", style="Panel.TLabel").pack(side="left")
        self.ip_box = ttk.Combobox(row, textvariable=self.ip_var, width=18)
        self.ip_box.pack(side="left", padx=(8, 14))
        ttk.Label(row, text="Port", style="Panel.TLabel").pack(side="left")
        self.port_entry = ttk.Entry(row, textvariable=self.port_var, width=7)
        self.port_entry.pack(side="left", padx=(8, 14))
        ttk.Button(row, text="Cari bulb", command=self.discover_devices).pack(side="left")
        self.scan_button = ttk.Button(
            row, text="Pindai subnet", command=self.scan_devices
        )
        self.scan_button.pack(side="left", padx=(8, 0))
        self.connect_button = ttk.Button(
            row, text="Hubungkan", style="Accent.TButton", command=self.connect
        )
        self.connect_button.pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Unlock LAN (miIO)", command=self.unlock_lan).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(row, text="Pairing Wi-Fi (Reset)", command=self.setup_wifi).pack(
            side="left", padx=(8, 0)
        )

        subnet_row = tk.Frame(connection, bg=PANEL, padx=14, pady=0)
        subnet_row.pack(fill="x", pady=(0, 10))
        ttk.Label(subnet_row, text="Subnet", style="Panel.TLabel").pack(side="left")
        ttk.Entry(subnet_row, textvariable=self.subnet_var, width=18).pack(
            side="left", padx=(8, 10)
        )
        ttk.Label(
            subnet_row,
            text="kosongkan = semua jaringan lokal · IP lampu berubah? klik Pindai subnet",
            style="PanelMuted.TLabel",
        ).pack(side="left")

        notebook = ttk.Notebook(outer)
        notebook.grid(row=2, column=0, sticky="nsew")
        self.notebook = notebook
        self._build_control_tab(notebook)
        self._build_effects_tab(notebook)
        self._build_diag_tab(notebook)
        self._build_info_tab(notebook)

        log_frame = tk.Frame(outer, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        log_frame.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        log_header = tk.Frame(log_frame, bg=PANEL)
        log_header.pack(fill="x", padx=12, pady=(8, 0))
        tk.Label(
            log_header,
            text="Log",
            bg=PANEL,
            fg=MUTED,
            font=("Segoe UI Semibold", 9),
        ).pack(side="left")
        tk.Button(
            log_header,
            text="Bersihkan",
            bg=PANEL,
            fg=MUTED,
            activebackground=PANEL2,
            activeforeground=FG,
            relief="flat",
            bd=0,
            font=("Segoe UI", 8),
            cursor="hand2",
            command=self._clear_log,
        ).pack(side="right")
        self.log_text = tk.Text(
            log_frame,
            height=6,
            bg=PANEL,
            fg=FG,
            insertbackground=FG,
            relief="flat",
            bd=0,
            padx=12,
            pady=6,
            font=("Consolas", 9),
            wrap="word",
        )
        self.log_text.pack(fill="x")
        self.log_text.tag_configure("ok", foreground=GREEN)
        self.log_text.tag_configure("error", foreground=RED)
        self.log_text.tag_configure("muted", foreground=MUTED)
        self.log_text.tag_configure("accent", foreground=ACCENT)
        self.log_text.configure(state="disabled")

    # ------------------------------------------------------------------- tabs

    def _page(self, notebook: ttk.Notebook) -> tk.Frame:
        page = tk.Frame(notebook, bg=BG, padx=12, pady=12)
        notebook.add(page, text="  Kontrol  ")
        return page

    def _card(self, parent: tk.Widget, title: str, subtitle: str = "") -> tuple[tk.Frame, tk.Frame]:
        card = tk.Frame(parent, bg=PANEL, highlightbackground=BORDER, highlightthickness=1)
        box = tk.Frame(card, bg=PANEL, padx=16, pady=14)
        box.pack(fill="both", expand=True)
        ttk.Label(box, text=title, style="H1.TLabel").pack(anchor="w")
        if subtitle:
            ttk.Label(box, text=subtitle, style="PanelMuted.TLabel").pack(
                anchor="w", pady=(2, 10)
            )
        else:
            tk.Frame(box, bg=PANEL, height=8).pack()
        return card, box

    def _build_control_tab(self, notebook: ttk.Notebook) -> None:
        page = self._page(notebook)
        page.grid_columnconfigure(0, weight=1, uniform="c")
        page.grid_columnconfigure(1, weight=1, uniform="c")
        page.grid_rowconfigure(2, weight=1)

        power_card, power = self._card(page, "Daya & kecerahan", "Kontrol utama lampu")
        power_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=(0, 12))
        self.power_button = tk.Button(
            power,
            text="Nyalakan lampu",
            bg=PANEL2,
            fg=FG,
            activebackground="#2c3547",
            activeforeground=FG,
            relief="flat",
            bd=0,
            padx=18,
            pady=13,
            font=("Segoe UI Semibold", 12),
            cursor="hand2",
            command=self.toggle_power,
        )
        self.power_button.pack(fill="x")
        self._controls.append(self.power_button)

        ttk.Label(power, text="Kecerahan", style="PanelMuted.TLabel").pack(
            anchor="w", pady=(16, 0)
        )
        bright_row = tk.Frame(power, bg=PANEL)
        bright_row.pack(fill="x")
        self.bright_scale = ttk.Scale(
            bright_row,
            from_=1,
            to=100,
            variable=self.bright_var,
            command=self._on_bright,
        )
        self.bright_scale.pack(side="left", fill="x", expand=True)
        ttk.Label(bright_row, textvariable=self.bright_label, style="Value.TLabel").pack(
            side="left", padx=(10, 0)
        )
        self._controls.append(self.bright_scale)
        quick = tk.Frame(power, bg=PANEL)
        quick.pack(fill="x", pady=(10, 0))
        for value in (10, 25, 50, 75, 100):
            button = ttk.Button(
                quick, text=f"{value}%", width=5, command=lambda v=value: self.set_bright(v)
            )
            button.pack(side="left", padx=(0, 5))
            self._controls.append(button)

        colour_card, colour = self._card(page, "Warna", "RGB, swatch, atau HSV")
        colour_card.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=(0, 12))
        swatch_row = tk.Frame(colour, bg=PANEL)
        swatch_row.pack(fill="x")
        self.swatch = tk.Canvas(
            swatch_row,
            width=66,
            height=66,
            bg=PANEL,
            highlightthickness=0,
            bd=0,
        )
        self.swatch.pack(side="left")
        self.swatch_rect = self.swatch.create_rectangle(
            2, 2, 64, 64, fill="#ffffff", outline=BORDER, width=2
        )
        info = tk.Frame(swatch_row, bg=PANEL)
        info.pack(side="left", padx=(12, 0), fill="x", expand=True)
        ttk.Label(info, textvariable=self.colour_label, style="Value.TLabel").pack(anchor="w")
        ttk.Button(info, text="Pilih warna…", command=self.pick_colour).pack(
            anchor="w", pady=(6, 0)
        )
        swatches = tk.Frame(colour, bg=PANEL)
        swatches.pack(fill="x", pady=(12, 0))
        for hex_colour, value in PRESET_COLOURS:
            button = tk.Button(
                swatches,
                bg=hex_colour,
                activebackground=hex_colour,
                width=3,
                height=1,
                relief="flat",
                bd=0,
                highlightthickness=1,
                highlightbackground=BORDER,
                cursor="hand2",
                command=lambda v=value, h=hex_colour: self.set_colour(v, h),
            )
            button.pack(side="left", padx=(0, 4))
            self._controls.append(button)

        hsv = tk.Frame(colour, bg=PANEL)
        hsv.pack(fill="x", pady=(12, 0))
        ttk.Label(hsv, text="H", style="PanelMuted.TLabel").pack(side="left")
        hue = ttk.Spinbox(hsv, from_=0, to=359, width=5, textvariable=self.hue_var)
        hue.pack(side="left", padx=(4, 10))
        ttk.Label(hsv, text="S", style="PanelMuted.TLabel").pack(side="left")
        sat = ttk.Spinbox(hsv, from_=0, to=100, width=5, textvariable=self.sat_var)
        sat.pack(side="left", padx=(4, 10))
        hsv_button = ttk.Button(hsv, text="Terapkan HSV", command=self.apply_hsv)
        hsv_button.pack(side="left")
        self._controls.extend([hue, sat, hsv_button])

        ct_card, ct = self._card(
            page, "Suhu warna", "Putih hangat 1700 K sampai dingin 6500 K"
        )
        ct_card.grid(row=2, column=0, columnspan=2, sticky="nsew")
        ct_row = tk.Frame(ct, bg=PANEL)
        ct_row.pack(fill="x")
        self.ct_scale = ttk.Scale(
            ct_row, from_=1700, to=6500, variable=self.ct_var, command=self._on_ct
        )
        self.ct_scale.pack(side="left", fill="x", expand=True)
        ttk.Label(ct_row, textvariable=self.ct_label, style="Value.TLabel").pack(
            side="left", padx=(10, 0)
        )
        self._controls.append(self.ct_scale)
        ct_quick = tk.Frame(ct, bg=PANEL)
        ct_quick.pack(fill="x", pady=(10, 0))
        for kelvin, label in ((1900, "Lilin"), (2700, "Hangat"), (4000, "Netral"), (5000, "Kerja"), (6500, "Dingin")):
            button = ttk.Button(
                ct_quick,
                text=f"{label} · {kelvin} K",
                command=lambda k=kelvin: self.set_ct(k),
            )
            button.pack(side="left", padx=(0, 6))
            self._controls.append(button)

    def _build_effects_tab(self, notebook: ttk.Notebook) -> None:
        page = self._page(notebook)
        notebook.tab(1, text="  Efek  ")
        page.grid_columnconfigure(0, weight=1, uniform="e")
        page.grid_columnconfigure(1, weight=1, uniform="e")
        page.grid_rowconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)

        scene_card, scene = self._card(page, "Scene", "Suasana siap pakai")
        scene_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=(0, 12))
        grid = tk.Frame(scene, bg=PANEL)
        grid.pack(fill="both", expand=True)
        for index, name in enumerate(SCENES):
            button = ttk.Button(
                grid,
                text=SCENE_LABELS.get(name, name.title()),
                command=lambda n=name: self.apply_scene(n),
            )
            button.grid(row=index // 3, column=index % 3, sticky="ew", padx=3, pady=3)
            self._controls.append(button)
        for column in range(3):
            grid.grid_columnconfigure(column, weight=1)
        ttk.Label(scene, textvariable=self.scene_hint, style="PanelMuted.TLabel").pack(
            anchor="w", pady=(8, 0)
        )

        flow_card, flow = self._card(page, "Flow", "Animasi yang disimpan di firmware")
        flow_card.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=(0, 12))
        flow_row = tk.Frame(flow, bg=PANEL)
        flow_row.pack(fill="x")
        self.flow_box = ttk.Combobox(
            flow_row,
            textvariable=self.flow_var,
            values=sorted(FLOW_PRESETS),
            state="readonly",
            width=12,
        )
        self.flow_box.pack(side="left")
        ttk.Label(flow_row, text="loop", style="PanelMuted.TLabel").pack(
            side="left", padx=(10, 4)
        )
        flow_count = ttk.Spinbox(flow_row, from_=0, to=9999, width=5, textvariable=self.flow_count_var)
        flow_count.pack(side="left")
        ttk.Label(flow_row, text="0 = terus-menerus", style="PanelMuted.TLabel").pack(
            side="left", padx=(8, 0)
        )
        flow_buttons = tk.Frame(flow, bg=PANEL)
        flow_buttons.pack(fill="x", pady=(10, 0))
        start = ttk.Button(
            flow_buttons, text="Jalankan flow", style="Accent.TButton", command=self.start_flow
        )
        start.pack(side="left")
        stop = ttk.Button(flow_buttons, text="Hentikan", command=self.stop_flow)
        stop.pack(side="left", padx=(8, 0))
        self._controls.extend([self.flow_box, flow_count, start, stop])

        music_card, music = self._card(
            page, "Music mode", "Latensi rendah, kuota command sementara dibuka"
        )
        music_card.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        music_row = tk.Frame(music, bg=PANEL)
        music_row.pack(fill="x")
        music_box = ttk.Combobox(
            music_row,
            textvariable=self.music_mode_var,
            values=("rainbow", "pulse", "white"),
            state="readonly",
            width=10,
        )
        music_box.pack(side="left")
        ttk.Label(music_row, text="detik", style="PanelMuted.TLabel").pack(
            side="left", padx=(10, 4)
        )
        music_seconds = ttk.Spinbox(
            music_row, from_=3, to=120, width=5, textvariable=self.music_seconds_var
        )
        music_seconds.pack(side="left")
        music_buttons = tk.Frame(music, bg=PANEL)
        music_buttons.pack(fill="x", pady=(10, 0))
        music_start = ttk.Button(
            music_buttons, text="Mulai demo", command=self.start_music
        )
        music_start.pack(side="left")
        music_stop = ttk.Button(music_buttons, text="Stop", command=self.stop_music)
        music_stop.pack(side="left", padx=(8, 0))
        self._controls.extend([music_box, music_seconds, music_start, music_stop])

        timer_card, timer = self._card(
            page, "Timer mati", "Matikan lampu otomatis setelah N menit"
        )
        timer_card.grid(row=1, column=1, sticky="nsew", padx=(6, 0))
        timer_row = tk.Frame(timer, bg=PANEL)
        timer_row.pack(fill="x")
        timer_spin = ttk.Spinbox(
            timer_row, from_=1, to=240, width=6, textvariable=self.timer_var
        )
        timer_spin.pack(side="left")
        ttk.Label(timer_row, text="menit", style="PanelMuted.TLabel").pack(
            side="left", padx=(8, 0)
        )
        timer_button = ttk.Button(
            timer_row,
            text="Pasang timer",
            style="Accent.TButton",
            command=self.set_timer,
        )
        timer_button.pack(side="left", padx=(12, 0))
        self._controls.extend([timer_spin, timer_button])
        ttk.Label(
            timer,
            text="Timer disimpan di firmware; tetap berjalan walau aplikasi ditutup.",
            style="PanelMuted.TLabel",
            wraplength=380,
            justify="left",
        ).pack(anchor="w", pady=(10, 0))

    def _build_diag_tab(self, notebook: ttk.Notebook) -> None:
        page = self._page(notebook)
        notebook.tab(2, text="  miIO & Diagnosa  ")
        explain, box = self._card(
            page,
            "Koneksi tanpa app",
            "Handshake miIO di UDP 54321, lalu buka TCP 55443 bila firmware mengizinkan.",
        )
        explain.pack(fill="x")
        buttons = tk.Frame(box, bg=PANEL)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Cek handshake", command=self.check_miio).pack(side="left")
        ttk.Button(
            buttons, text="Unlock LAN Control", style="Accent.TButton", command=self.unlock_lan
        ).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Diagnosa lengkap", command=self.run_diagnostics).pack(
            side="left", padx=(8, 0)
        )
        token_row = tk.Frame(box, bg=PANEL)
        token_row.pack(fill="x", pady=(10, 0))
        ttk.Label(token_row, text="Token (opsional)", style="PanelMuted.TLabel").pack(
            side="left"
        )
        token_entry = ttk.Entry(token_row, textvariable=self.token_var, width=38)
        token_entry.pack(side="left", padx=(8, 0))
        ttk.Label(
            box,
            text=(
                "Token hanya diperlukan kalau firmware mengembalikan 0x00 saat handshake. "
                "Tool ini tidak mengambil token dari cloud."
            ),
            style="PanelMuted.TLabel",
            wraplength=760,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

        output_card, output = self._card(page, "Hasil", "Output diagnostika")
        output_card.pack(fill="both", expand=True, pady=(12, 0))
        self.diag_text = tk.Text(
            output,
            height=12,
            bg=FIELD,
            fg=FG,
            insertbackground=FG,
            relief="flat",
            bd=0,
            padx=10,
            pady=8,
            font=("Consolas", 9),
            wrap="word",
        )
        self.diag_text.pack(fill="both", expand=True)
        self.diag_text.tag_configure("ok", foreground=GREEN)
        self.diag_text.tag_configure("error", foreground=RED)
        self.diag_text.tag_configure("muted", foreground=MUTED)
        self.diag_text.configure(state="disabled")

    def _build_info_tab(self, notebook: ttk.Notebook) -> None:
        page = self._page(notebook)
        notebook.tab(3, text="  Info & Raw  ")
        page.grid_columnconfigure(0, weight=1, uniform="i")
        page.grid_columnconfigure(1, weight=1, uniform="i")
        page.grid_rowconfigure(1, weight=1)

        info_card, info = self._card(page, "Perangkat", "Data dari SSDP dan API LAN")
        info_card.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=(0, 12))
        self.info_labels: dict[str, tk.StringVar] = {
            "ip": tk.StringVar(value="—"),
            "model": tk.StringVar(value="—"),
            "firmware": tk.StringVar(value="—"),
            "name": tk.StringVar(value="—"),
            "support": tk.StringVar(value="—"),
        }
        info_grid = tk.Frame(info, bg=PANEL)
        info_grid.pack(fill="both", expand=True)
        for row_index, (key, label) in enumerate(
            (
                ("ip", "Alamat"),
                ("model", "Model"),
                ("firmware", "Firmware"),
                ("name", "Nama"),
                ("support", "Method"),
            )
        ):
            ttk.Label(info_grid, text=label, style="PanelMuted.TLabel").grid(
                row=row_index, column=0, sticky="w", pady=2
            )
            ttk.Label(
                info_grid,
                textvariable=self.info_labels[key],
                style="Panel.TLabel",
                wraplength=360,
                justify="left",
            ).grid(row=row_index, column=1, sticky="w", padx=(12, 0), pady=2)
        info_grid.grid_columnconfigure(1, weight=1)

        rename_card, rename = self._card(page, "Ganti nama", "Nama tampil di app dan notifikasi")
        rename_card.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=(0, 12))
        rename_row = tk.Frame(rename, bg=PANEL)
        rename_row.pack(fill="x")
        rename_entry = ttk.Entry(rename_row, textvariable=self.rename_var)
        rename_entry.pack(side="left", fill="x", expand=True)
        rename_button = ttk.Button(rename_row, text="Simpan", command=self.rename_bulb)
        rename_button.pack(side="left", padx=(8, 0))
        self._controls.extend([rename_entry, rename_button])
        ttk.Label(
            rename,
            text="Nama disimpan di firmware, bukan di akun.",
            style="PanelMuted.TLabel",
        ).pack(anchor="w", pady=(8, 0))

        raw_card, raw = self._card(page, "Raw command", "Untuk reverse engineering")
        raw_card.grid(row=1, column=0, columnspan=2, sticky="nsew")
        raw_row = tk.Frame(raw, bg=PANEL)
        raw_row.pack(fill="x")
        raw_method = ttk.Entry(raw_row, textvariable=self.raw_method_var, width=18)
        raw_method.pack(side="left")
        raw_params = ttk.Entry(raw_row, textvariable=self.raw_params_var)
        raw_params.pack(side="left", fill="x", expand=True, padx=(8, 8))
        raw_button = ttk.Button(raw_row, text="Kirim", command=self.send_raw)
        raw_button.pack(side="left")
        raw_help = ttk.Button(
            raw_row,
            text="Bantuan",
            command=lambda: self.log(
                'Contoh: set_scene ["color", 16711680, 100]; set_power ["on"]', "muted"
            ),
        )
        raw_help.pack(side="left", padx=(8, 0))
        self._controls.extend([raw_method, raw_params, raw_button])
        ttk.Label(
            raw,
            text="Params harus JSON array. Method dan hasilnya tercatat di log bawah.",
            style="PanelMuted.TLabel",
        ).pack(anchor="w", pady=(8, 0))

    # ------------------------------------------------------------------ utils

    def _controls_list(self) -> list[tk.Widget]:
        return self._controls

    def _set_controls_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        for widget in self._controls:
            try:
                # pyrefly: ignore[unexpected-keyword]
                widget.configure(state=state)
            except tk.TclError:
                pass
        self.connect_button.configure(state="normal")

    def _set_status(self, text: str, colour: str) -> None:
        self.status_var.set(text)
        self.status_label.configure(fg=colour)

    def _post(self, callback: Callable[..., Any], *args: Any) -> None:
        self._queue.put((callback, args))

    def _drain(self) -> None:
        try:
            while True:
                callback, args = self._queue.get_nowait()
                try:
                    callback(*args)
                except Exception as exc:  # a GUI callback must not kill the loop
                    self.log(f"GUI error: {exc}", "error")
        except queue.Empty:
            pass
        if not self._closing:
            self.after(50, self._drain)

    def _run(
        self,
        work: Callable[[], Any],
        done: Callable[[Any], None] | None = None,
        error: Callable[[Exception], None] | None = None,
    ) -> None:
        def runner() -> None:
            try:
                result = work()
            except Exception as exc:
                self._post(error or (lambda e: self.log(str(e), "error")), exc)
            else:
                if done is not None:
                    self._post(done, result)

        threading.Thread(target=runner, daemon=True).start()

    def log(self, text: str, level: str = "info") -> None:
        stamp = time.strftime("%H:%M:%S")
        self.log_text.configure(state="normal")
        self.log_text.insert("end", f"{stamp}  {text}\n", level)
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _clear_log(self) -> None:
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")

    def diag(self, text: str, level: str = "info") -> None:
        self.diag_text.configure(state="normal")
        self.diag_text.insert("end", text + "\n", level)
        self.diag_text.see("end")
        self.diag_text.configure(state="disabled")

    # -------------------------------------------------------------- connection

    def discover_devices(self) -> None:
        self.log("Mencari bulb lewat SSDP…", "muted")
        self._set_status("Mencari…", ACCENT)

        def work() -> list[Any]:
            return unique_by_ip(discover(timeout=3.0))

        def done(devices: list[Any]) -> None:
            self.devices = {device.ip: device for device in devices}
            values = [f"{device.ip}" for device in devices]
            self.ip_box.configure(values=values)
            if devices:
                if not self.ip_var.get().strip():
                    self.ip_var.set(devices[0].ip)
                for device in devices:
                    self.log(
                        f"Ditemukan {device.ip} · {device.model or '?'} · "
                        f"{device.name or '(tanpa nama)'} · fw {device.fw_ver or '?'}",
                        "ok",
                    )
                self._set_status("Ditemukan, siap dihubungkan", MUTED)
            else:
                self.log(
                    "Tidak ada jawaban SSDP. Coba isi IP manual atau aktifkan LAN Control.",
                    "error",
                )
                self._set_status("Tidak ditemukan", RED)

        def failed(exc: Exception) -> None:
            self.log(f"Discovery gagal: {exc}", "error")
            self._set_status("Discovery gagal", RED)

        self._run(work, done, failed)

    def scan_devices(self) -> None:
        """Walk the whole subnet over TCP 55443 — the cure for a changed IP."""
        subnet = self.subnet_var.get().strip() or None
        self.scan_button.configure(state="disabled")
        self._set_status("Memindai subnet…", ACCENT)
        self.log(
            f"Memindai {subnet or 'semua jaringan lokal (/24)'} pada TCP {CONTROL_PORT}… "
            "bisa 5-20 detik.",
            "muted",
        )

        def work() -> list[Any]:
            return scan_lan(subnet, timeout=0.25, identify_timeout=2.0)

        def done(hits: list[Any]) -> None:
            self.scan_button.configure(state="normal")
            bulbs = [hit for hit in hits if hit.is_bulb]
            others = [hit for hit in hits if not hit.is_bulb]
            if bulbs:
                self.ip_box.configure(values=[hit.ip for hit in bulbs])
                for hit in bulbs:
                    self.log(f"Lampu ditemukan: {hit.label}", "ok")
                for hit in others:
                    self.log(f"Port terbuka, bukan Yeelight: {hit.ip}", "muted")

                current = self.ip_var.get().strip()
                if len(bulbs) == 1:
                    hit = bulbs[0]
                    if current and current != hit.ip:
                        self.log(f"IP berubah: {current} → {hit.ip}. Menghubungkan ulang…", "accent")
                    self.ip_var.set(hit.ip)
                    self._set_status("Lampu ditemukan, menghubungkan…", ACCENT)
                    self.connect(interactive=False)
                    return
                if current not in {hit.ip for hit in bulbs}:
                    self.ip_var.set(bulbs[0].ip)
                self._set_status(f"{len(bulbs)} lampu ditemukan", MUTED)
                self.log(
                    "Lebih dari satu lampu ditemukan — pilih IP di kotak lalu klik Hubungkan.",
                    "muted",
                )
                return

            self._set_status("Tidak ada lampu", RED)
            if others:
                self.log(
                    "Port 55443 terbuka di "
                    + ", ".join(hit.ip for hit in others)
                    + " tapi tidak ada yang menjawab sebagai Yeelight.",
                    "error",
                )
            else:
                self.log(
                    "Tidak ada host dengan TCP 55443 di jaringan ini. "
                    "Pastikan PC dan lampu satu jaringan, lalu isi subnet manual "
                    "(mis. 192.168.1.0/24).",
                    "error",
                )

        def failed(exc: Exception) -> None:
            self.scan_button.configure(state="normal")
            self._set_status("Pindai gagal", RED)
            self.log(f"Pindai subnet gagal: {exc}", "error")

        self._run(work, done, failed)

    def connect(self, interactive: bool = True, fallback_scan: bool = False) -> None:
        ip = self.ip_var.get().strip()
        if not ip:
            if fallback_scan:
                self.scan_devices()
            else:
                messagebox.showwarning("IP kosong", "Masukkan IP bulb atau klik Cari bulb.")
            return
        try:
            port = int(self.port_var.get())
        except ValueError:
            port = CONTROL_PORT
            self.port_var.set(str(port))
        self._save_settings()
        self.log(f"Menghubungkan ke {ip}:{port}…", "muted")
        self._set_status("Menghubungkan…", ACCENT)
        self.connect_button.configure(state="disabled")

        def work() -> tuple[YeelightClient, dict[str, Any]]:
            client = YeelightClient(ip, port, timeout=4.0)
            status = client.status()
            return client, status

        def done(result: tuple[YeelightClient, dict[str, Any]]) -> None:
            client, status = result
            self._connected(client, status)

        def failed(exc: Exception) -> None:
            self.connect_button.configure(state="normal")
            if isinstance(exc, LanControlDisabled):
                self._set_status("LAN Control OFF", RED)
                self.log(
                    "TCP 55443 menolak. LAN Control belum aktif; mencoba jalur miIO…",
                    "error",
                )
                if interactive and messagebox.askyesno(
                    "LAN Control OFF",
                    "Port 55443 menolak koneksi.\n\n"
                    "Coba buka LAN Control lewat miIO sekarang?\n"
                    "(tanpa membuka app, tanpa cloud)",
                ):
                    self.unlock_lan()
            else:
                self._set_status("Gagal terhubung", RED)
                self.log(f"Koneksi gagal ke {ip}: {exc}", "error")
                if fallback_scan and not self._closing:
                    self.log("IP tersimpan tidak menjawab. Memindai subnet otomatis…", "muted")
                    self.scan_devices()
                    return
                self.log(
                    "Kalau IP lampu berubah, klik Pindai subnet untuk mencarinya lagi.",
                    "muted",
                )
                if interactive:
                    messagebox.showerror(
                        "Tidak bisa terhubung",
                        f"{exc}\n\nPeriksa IP, jaringan 2.4 GHz, dan firewall.\n"
                        "IP lampu dinamis? Klik “Pindai subnet”.",
                    )

        self._run(work, done, failed)

    def _connected(self, client: YeelightClient, status: dict[str, Any]) -> None:
        if self.client is not None and self.client is not client:
            try:
                self.client.close()
            except Exception:
                pass
        self.client = client
        self.connected = True
        self.client.add_listener(self._on_notification)
        self._set_controls_enabled(True)
        self.connect_button.configure(state="normal")
        self._update_state(status)
        ip = self.ip_var.get().strip()
        self._set_status(f"Terhubung · {ip}", GREEN)
        self.log(f"Terhubung ke {ip}. State awal diterima.", "ok")
        self._refresh_device_info()
        self._schedule_poll()

    def _on_notification(self, props: dict[str, Any]) -> None:
        self._post(self._update_state, props)

    def _schedule_poll(self) -> None:
        if self._poll_job is not None:
            try:
                self.after_cancel(self._poll_job)
            except tk.TclError:
                pass
        self._poll_job = self.after(5000, self._poll_status)

    def _poll_status(self) -> None:
        self._poll_job = None
        client = self.client
        if client is None or self._closing:
            return

        def done(status: dict[str, Any]) -> None:
            if client is self.client:
                self._update_state(status)

        self._run(client.status, done, self._poll_failed)
        self._schedule_poll()

    def _poll_failed(self, exc: Exception) -> None:
        if self._closing:
            return
        was_connected = self.connected
        self.connected = False
        self._set_status("Terputus", RED)
        self.log(f"Polling gagal: {exc}", "error")
        if was_connected:
            self.log(
                "Lampu tidak menjawab lagi. Kalau IP-nya berubah, klik Pindai subnet "
                "untuk menemukannya kembali.",
                "muted",
            )

    def _refresh_device_info(self) -> None:
        ip = self.ip_var.get().strip()
        device = self.devices.get(ip)
        if device is not None:
            self._apply_device(device)
            return

        def work() -> list[Any]:
            return unique_by_ip(discover(timeout=2.0))

        def done(devices: list[Any]) -> None:
            self.devices = {item.ip: item for item in devices}
            self.ip_box.configure(values=[item.ip for item in devices])
            device = self.devices.get(ip)
            if device is not None:
                self._apply_device(device)

        self._run(work, done)

    def _apply_device(self, device: Any) -> None:
        self.info_labels["ip"].set(f"{device.ip}:{device.port}")
        self.info_labels["model"].set(device.model or "—")
        self.info_labels["firmware"].set(device.fw_ver or "—")
        self.info_labels["name"].set(device.name or "—")
        support = list(device.support)
        self.info_labels["support"].set(
            ", ".join(support[:6]) + ("…" if len(support) > 6 else "") if support else "—"
        )

    # ------------------------------------------------------------------ state

    def _update_state(self, props: dict[str, Any]) -> None:
        if not isinstance(props, dict):
            return
        for key, value in props.items():
            if key in INT_PROPS:
                try:
                    value = int(value)
                except (TypeError, ValueError):
                    continue
            self.state[key] = value

        power = str(self.state.get("power", "off"))
        if power == "on":
            self.power_button.configure(
                text="Matikan lampu", bg=GREEN, fg="#08120c", activebackground="#63e6a8"
            )
        else:
            self.power_button.configure(
                text="Nyalakan lampu", bg=PANEL2, fg=FG, activebackground="#2c3547"
            )

        self._syncing = True
        try:
            bright = self.state.get("bright")
            if isinstance(bright, int):
                self.bright_var.set(bright)
                self.bright_label.set(f"{bright}%")
            ct = self.state.get("ct")
            if isinstance(ct, int):
                self.ct_var.set(ct)
                self.ct_label.set(f"{ct} K")
            rgb = self.state.get("rgb")
            if isinstance(rgb, int):
                self._paint_colour(rgb)
            hue = self.state.get("hue")
            sat = self.state.get("sat")
            if isinstance(hue, int):
                self.hue_var.set(str(hue))
            if isinstance(sat, int):
                self.sat_var.set(str(sat))
            name = self.state.get("name")
            if name:
                self.rename_var.set(str(name))
                self.info_labels["name"].set(str(name))
        finally:
            self.after(80, self._end_sync)

    def _end_sync(self) -> None:
        self._syncing = False

    def _paint_colour(self, rgb: int) -> None:
        hex_colour = rgb_to_hex(rgb)
        self.swatch.itemconfigure(self.swatch_rect, fill=hex_colour)
        self.colour_label.set(hex_colour)

    # --------------------------------------------------------------- commands

    def _send(self, method: str, params: list[Any] | None = None) -> None:
        client = self.client
        if client is None or not self.connected:
            self.log("Belum terhubung ke bulb.", "error")
            return

        def done(result: Any) -> None:
            if method not in ("set_bright", "set_ct_abx", "set_rgb", "set_hsv"):
                self.log(f"{method} → {json.dumps(result, ensure_ascii=False)}", "muted")
            if method in ("set_name",):
                self.info_labels["name"].set(self.rename_var.get())
            self.after(350, self._refresh_once)

        def failed(exc: Exception) -> None:
            self.log(f"{method} gagal: {exc}", "error")

        self._run(lambda: client.send(method, params or []), done, failed)

    def _refresh_once(self) -> None:
        client = self.client
        if client is None or not self.connected:
            return
        self._run(client.status, self._update_state, self._poll_failed)

    def toggle_power(self) -> None:
        client = self.client
        if client is None or not self.connected:
            self.log("Belum terhubung ke bulb.", "error")
            return
        turn_on = str(self.state.get("power")) != "on"
        self._run(lambda: client.set_power(turn_on), None, self._command_failed)

    def _command_failed(self, exc: Exception) -> None:
        self.log(str(exc), "error")

    def set_bright(self, value: int) -> None:
        value = clamp(value, 1, 100)
        self.bright_var.set(value)
        self.bright_label.set(f"{value}%")
        self._send("set_bright", [value])

    def _on_bright(self, value: str) -> None:
        level = int(float(value))
        self.bright_label.set(f"{level}%")
        if self._syncing:
            return
        if self._bright_job is not None:
            try:
                self.after_cancel(self._bright_job)
            except tk.TclError:
                pass
        self._bright_job = self.after(320, lambda: self._commit_bright(level))

    def _commit_bright(self, level: int) -> None:
        self._bright_job = None
        if not self._syncing:
            self._send("set_bright", [clamp(level, 1, 100)])

    def set_ct(self, kelvin: int) -> None:
        kelvin = clamp(kelvin, 1700, 6500)
        self.ct_var.set(kelvin)
        self.ct_label.set(f"{kelvin} K")
        self._send("set_ct_abx", [kelvin, "smooth", 300])

    def _on_ct(self, value: str) -> None:
        kelvin = int(float(value))
        self.ct_label.set(f"{kelvin} K")
        if self._syncing:
            return
        if self._ct_job is not None:
            try:
                self.after_cancel(self._ct_job)
            except tk.TclError:
                pass
        self._ct_job = self.after(320, lambda: self._commit_ct(kelvin))

    def _commit_ct(self, kelvin: int) -> None:
        self._ct_job = None
        if not self._syncing:
            self._send("set_ct_abx", [clamp(kelvin, 1700, 6500), "smooth", 300])

    def pick_colour(self) -> None:
        rgb = self.state.get("rgb")
        initial = rgb_to_hex(rgb) if isinstance(rgb, int) else "#ffffff"
        chosen, hex_colour = colorchooser.askcolor(color=initial, title="Pilih warna lampu")
        if hex_colour is None or chosen is None:
            return
        value = (int(chosen[0]) << 16) | (int(chosen[1]) << 8) | int(chosen[2])
        self.set_colour(value, hex_colour)

    def set_colour(self, value: int, hex_colour: str | None = None) -> None:
        self._paint_colour(value)
        self._send("set_rgb", [value, "smooth", 300])
        self.log(f"Warna {hex_colour or rgb_to_hex(value)}", "muted")

    def apply_hsv(self) -> None:
        try:
            hue = clamp(int(self.hue_var.get()), 0, 359)
            sat = clamp(int(self.sat_var.get()), 0, 100)
        except ValueError:
            messagebox.showwarning("HSV", "Hue dan saturation harus angka.")
            return
        self._send("set_hsv", [hue, sat, "smooth", 300])
        red, green, blue = colorsys.hsv_to_rgb(hue / 360.0, sat / 100.0, 1.0)
        self._paint_colour(
            (round(red * 255) << 16) | (round(green * 255) << 8) | round(blue * 255)
        )

    def apply_scene(self, name: str) -> None:
        params = SCENES.get(name)
        if params is None:
            return
        self.scene_hint.set(f"Scene: {SCENE_LABELS.get(name, name)}")
        self._send("set_scene", list(params))
        self.log(f"Scene {name} diterapkan.", "muted")

    def start_flow(self) -> None:
        name = self.flow_var.get()
        try:
            count, action, expression = flow_params(name)
            loop = int(self.flow_count_var.get())
        except (ValueError, KeyError):
            messagebox.showwarning("Flow", "Pilih preset flow yang valid.")
            return
        if loop < 0:
            loop = 0
        self._send("start_cf", [loop, action, expression])
        self.log(f"Flow {name} dimulai (loop={loop or '∞'}).", "ok")

    def stop_flow(self) -> None:
        self._send("stop_cf", [])

    def set_timer(self) -> None:
        try:
            minutes = clamp(int(self.timer_var.get()), 1, 240)
        except ValueError:
            messagebox.showwarning("Timer", "Masukkan jumlah menit.")
            return
        bright = self.state.get("bright")
        if not isinstance(bright, int):
            bright = 100
        # auto_delay_off: brightness, minutes
        self._send("set_scene", ["auto_delay_off", bright, minutes])
        self.log(f"Timer mati dipasang: {minutes} menit.", "ok")

    def rename_bulb(self) -> None:
        name = self.rename_var.get().strip()
        if not name:
            messagebox.showwarning("Nama", "Nama tidak boleh kosong.")
            return
        self._send("set_name", [name])
        self.log(f"Nama diubah menjadi “{name}”.", "ok")

    def send_raw(self) -> None:
        method = self.raw_method_var.get().strip()
        if not method:
            messagebox.showwarning("Raw", "Isi method.")
            return
        try:
            params = json.loads(self.raw_params_var.get() or "[]")
        except json.JSONDecodeError as exc:
            messagebox.showerror("Raw", f"Params bukan JSON valid: {exc}")
            return
        if not isinstance(params, list):
            messagebox.showerror("Raw", "Params harus JSON array.")
            return
        self._send(method, params)

    # -------------------------------------------------------------- music mode

    def start_music(self) -> None:
        client = self.client
        if client is None or not self.connected:
            self.log("Belum terhubung.", "error")
            return
        if self._music_thread is not None and self._music_thread.is_alive():
            self.log("Music mode sudah berjalan.", "muted")
            return
        try:
            seconds = clamp(int(self.music_seconds_var.get()), 3, 120)
        except ValueError:
            seconds = 15
        mode = self.music_mode_var.get()
        self._music_stop.clear()

        def work() -> None:
            fps = 20.0
            frames = int(seconds * fps)
            try:
                with MusicMode(client) as music:
                    self._post(self.log, f"Music mode aktif ({mode}, {seconds}s).", "ok")
                    for frame in range(frames):
                        if self._music_stop.is_set():
                            break
                        if mode == "rainbow":
                            hue = (frame * 360.0 / max(1.0, fps * 2)) % 360.0
                            red, green, blue = colorsys.hsv_to_rgb(hue / 360.0, 1.0, 1.0)
                        elif mode == "pulse":
                            level = 0.15 + 0.85 * (
                                0.5 + 0.5 * math.sin(frame / max(1.0, fps))
                            )
                            red, green, blue = colorsys.hsv_to_rgb(0.08, 0.7, level)
                        else:
                            red = green = blue = 1.0
                        rgb = (
                            (round(red * 255) << 16)
                            | (round(green * 255) << 8)
                            | round(blue * 255)
                        )
                        client.set_rgb(rgb, "sudden", 0)
                        time.sleep(1.0 / fps)
                    drained = 0
                    while music.get(timeout=0.01) is not None:
                        drained += 1
                self._post(self.log, "Music mode selesai.", "muted")
            except Exception as exc:
                self._post(self.log, f"Music mode gagal: {exc}", "error")
            finally:
                self._post(self._music_finished)

        self._music_thread = threading.Thread(target=work, daemon=True)
        self._music_thread.start()

    def _music_finished(self) -> None:
        self._music_thread = None

    def stop_music(self) -> None:
        if self._music_thread is None:
            self.log("Music mode tidak sedang berjalan.", "muted")
            return
        self._music_stop.set()
        self.log("Menghentikan music mode…", "muted")

    # ---------------------------------------------------------------- miIO ops

    def check_miio(self) -> None:
        ip = self.ip_var.get().strip()
        if not ip:
            messagebox.showwarning("IP kosong", "Masukkan IP bulb.")
            return
        self.log(f"Handshake miIO ke {ip}:54321…", "muted")
        self._set_status("miIO handshake…", ACCENT)

        def done(info: dict[str, Any]) -> None:
            if not info["available"]:
                self._set_status("miIO tidak menjawab", RED)
                self.log(f"miIO gagal: {info['error']}", "error")
                self.diag(f"miIO {ip}: TIDAK MENJAWAB", "error")
                self.diag(str(info["error"]), "muted")
                return
            self.diag(f"miIO {ip}: OK (device 0x{info['device_id']})", "ok")
            if info["token_exposed"]:
                self._set_status("miIO siap", GREEN)
                self.log("miIO menjawab dan token tersedia.", "ok")
                self.diag(f"Token: {info['token']}", "ok")
                self.token_var.set(info["token"])
            else:
                self._set_status("miIO tanpa token", MUTED)
                self.log("miIO menjawab, tetapi token tidak dibocorkan.", "muted")
                self.diag("Token: tidak tersedia (0x00)", "muted")
            self.notebook.select(2)

        def failed(exc: Exception) -> None:
            self._set_status("miIO gagal", RED)
            self.log(f"miIO gagal: {exc}", "error")

        self._run(lambda: miio_probe(ip, timeout=2.5), done, failed)

    def unlock_lan(self) -> None:
        ip = self.ip_var.get().strip()
        if not ip:
            messagebox.showwarning("IP kosong", "Masukkan IP bulb.")
            return
        token = self.token_var.get().strip() or None
        self.log(f"Memeriksa miIO {ip}…", "muted")
        self._set_status("Unlock: handshake…", ACCENT)

        def probed(info: dict[str, Any]) -> None:
            if not info["available"]:
                self._set_status("miIO tidak menjawab", RED)
                self.log(f"miIO tidak menjawab: {info['error']}", "error")
                messagebox.showerror(
                    "miIO tidak menjawab",
                    f"Tidak ada balasan dari {ip}:54321.\n\n"
                    "Pastikan bulb dan komputer di jaringan yang sama, "
                    "dan firmware membuka miIO.",
                )
                return
            self.diag(f"miIO {ip}: OK (device 0x{info['device_id']})", "ok")
            use_token = token
            if info["token_exposed"] and not use_token:
                use_token = info["token"]
                self.token_var.set(info["token"])
            if not info["token_exposed"] and not use_token:
                self.log("Token tidak dibocorkan; meminta token manual.", "muted")
                entered = simpledialog.askstring(
                    "Token miIO",
                    "Firmware tidak membocorkan token.\n"
                    "Tempel token 32 karakter hex (opsional):",
                    parent=self,
                )
                if not entered:
                    self._set_status("Unlock dibatalkan", MUTED)
                    self.log("Unlock dibatalkan: token tidak tersedia.", "error")
                    return
                use_token = entered.strip()
                self.token_var.set(use_token)
            self._set_status("Unlock: set_ps…", ACCENT)

            def report(result: dict[str, Any]) -> None:
                self.diag(f"set_ps cfg_lan_ctrl=1 → {result['result']}", "ok" if result["lan_control"] else "muted")
                if result["lan_control"]:
                    self._set_status("LAN Control aktif", GREEN)
                    self.log("LAN Control aktif. Menghubungkan ulang…", "ok")
                    self.after(600, self.connect)
                else:
                    self._set_status("Port masih tertutup", RED)
                    self.log(
                        "Perintah diterima, tetapi TCP 55443 tetap tertutup. "
                        "Firmware ini mungkin memakai parameter lain.",
                        "error",
                    )
                    messagebox.showwarning(
                        "Belum berhasil",
                        "set_ps diterima, tetapi port 55443 masih tertutup.\n\n"
                        "Coba app resmi sekali atau jalur hardware "
                        "(docs/TANPA-LOGIN.md).",
                    )

            def unlock_failed(exc: Exception) -> None:
                self._set_status("Unlock gagal", RED)
                self.log(f"Unlock gagal: {exc}", "error")
                if isinstance(exc, MiioTokenError):
                    detail = (
                        "Token tidak tersedia atau ditolak.\n\n"
                        "Kalau handshake mengembalikan 0x00, isi token perangkat "
                        "secara manual di kolom Token."
                    )
                elif isinstance(exc, MiioError):
                    detail = str(exc)
                else:
                    detail = f"Kesalahan tak terduga:\n{exc}"
                messagebox.showerror("Unlock gagal", detail)

            self._run(
                lambda: enable_lan_control(
                    ip,
                    token=use_token,
                    port=MIIO_PORT,
                    control_port=int(self._port()),
                    timeout=3.0,
                ),
                report,
                unlock_failed,
            )

        self._run(lambda: miio_probe(ip, timeout=2.5), probed, lambda exc: self.log(str(exc), "error"))

    def setup_wifi(self) -> None:
        """Provision Wi-Fi credentials to a bulb in AP mode (e.g. 192.168.10.1)."""
        ip = self.ip_var.get().strip() or "192.168.10.1"
        ssid = simpledialog.askstring(
            "Pairing Wi-Fi (Reset)",
            "Pastikan PC terhubung ke Wi-Fi lampu (yeelink-light-..._miap).\n\n"
            "Nama Wi-Fi rumah (SSID 2.4 GHz):",
            initialvalue="WIFI LIA",
            parent=self,
        )
        if not ssid:
            return
        password = simpledialog.askstring(
            "Password Wi-Fi",
            f"Password untuk '{ssid}':",
            show="*",
            parent=self,
        )
        if password is None:
            return

        self.log(f"Mengirim konfigurasi Wi-Fi '{ssid}' ke {ip}…", "accent")
        self._set_status("Pairing Wi-Fi…", ACCENT)

        def do_provision() -> dict[str, Any]:
            from .miio import provision_wifi

            return provision_wifi(
                host=ip,
                ssid=ssid.strip(),
                password=password.strip(),
                token=self.token_var.get().strip() or None,
            )

        def on_done(res: dict[str, Any]) -> None:
            self._set_status("Pairing Wi-Fi OK", GREEN)
            self.log(f"Wi-Fi berhasil dikonfigurasi ke '{ssid}'!", "ok")
            messagebox.showinfo(
                "Pairing Berhasil",
                f"Konfigurasi Wi-Fi '{ssid}' berhasil diterima lampu!\n\n"
                "1. Hotspot lampu akan mati dan lampu bergabung ke Wi-Fi rumah Anda.\n"
                "2. Sambungkan kembali PC Anda ke Wi-Fi '{ssid}'.\n"
                "3. Klik tombol 'Cari bulb' untuk menemukan IP baru lampu.",
            )

        def on_fail(exc: Exception) -> None:
            self._set_status("Pairing gagal", RED)
            self.log(f"Pairing Wi-Fi gagal: {exc}", "error")
            messagebox.showerror(
                "Pairing Gagal",
                f"Gagal mengirim konfigurasi Wi-Fi:\n{exc}\n\n"
                "Pastikan PC tersambung ke hotspot Wi-Fi lampu (192.168.10.1).",
            )

        self._run(do_provision, on_done, on_fail)

    def _port(self) -> int:
        try:
            return int(self.port_var.get())
        except ValueError:
            return CONTROL_PORT

    # -------------------------------------------------------------- diagnostics

    def run_diagnostics(self) -> None:
        ip = self.ip_var.get().strip()
        if not ip:
            messagebox.showwarning("IP kosong", "Masukkan IP bulb.")
            return
        port = self._port()
        self.diag_text.configure(state="normal")
        self.diag_text.delete("1.0", "end")
        self.diag_text.configure(state="disabled")
        self.log("Menjalankan diagnosa lengkap…", "muted")
        self._set_status("Diagnosa…", ACCENT)

        def work() -> list[tuple[str, str]]:
            lines: list[tuple[str, str]] = []
            lines.append((f"Local IPv4: {local_ipv4() or 'unknown'}", "muted"))
            devices = unique_by_ip(discover(timeout=2.0))
            if devices:
                lines.append((f"SSDP: OK ({len(devices)} perangkat)", "ok"))
                for device in devices:
                    lines.append(
                        (
                            f"  {device.ip}:{device.port}  {device.model or '?'}  "
                            f"fw {device.fw_ver or '?'}  {device.name or ''}",
                            "info",
                        )
                    )
            else:
                lines.append(("SSDP: tidak ada jawaban", "error"))
            open_port, reason = probe_port(ip, port, timeout=2.0)
            if open_port:
                lines.append((f"TCP {port}: OK", "ok"))
                try:
                    client = YeelightClient(ip, port, timeout=3.0)
                    status = client.status()
                    client.close()
                    lines.append((f"LAN API: OK · power={status.get('power')} · bright={status.get('bright')}", "ok"))
                    lines.append((f"Nama: {status.get('name') or '(kosong)'} · CT={status.get('ct')} K", "info"))
                except YeelightError as exc:
                    lines.append((f"LAN API: gagal · {exc}", "error"))
            else:
                lines.append((f"TCP {port}: FAIL · {reason}", "error"))
            miio = miio_probe(ip, timeout=2.0)
            if miio["available"]:
                lines.append((f"miIO UDP 54321: OK (device 0x{miio['device_id']})", "ok"))
                if miio["token_exposed"]:
                    lines.append(("Token miIO: tersedia lewat handshake", "ok"))
                    lines.append((f"  {miio['token']}", "muted"))
                else:
                    lines.append(("Token miIO: tidak dibocorkan (0x00)", "muted"))
            else:
                lines.append((f"miIO UDP 54321: tidak menjawab · {miio['error']}", "muted"))
            return lines

        def done(lines: list[tuple[str, str]]) -> None:
            for text, level in lines:
                self.diag(text, level)
            self._set_status("Diagnosa selesai", MUTED)
            self.log("Diagnosa selesai.", "muted")
            self.notebook.select(2)

        self._run(work, done, lambda exc: self.log(f"Diagnosa gagal: {exc}", "error"))

    # ------------------------------------------------------------------- close

    def _on_close(self) -> None:
        self._closing = True
        self._music_stop.set()
        if self._poll_job is not None:
            try:
                self.after_cancel(self._poll_job)
            except tk.TclError:
                pass
        if self.client is not None:
            try:
                self.client.close()
            except Exception:
                pass
        self.destroy()


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    ip = None
    port = CONTROL_PORT
    index = 0
    while index < len(arguments):
        value = arguments[index]
        if value in ("--ip", "-i") and index + 1 < len(arguments):
            ip = arguments[index + 1]
            index += 2
        elif value in ("--port", "-p") and index + 1 < len(arguments):
            try:
                port = int(arguments[index + 1])
            except ValueError:
                port = CONTROL_PORT
            index += 2
        elif value in ("--help", "-h"):
            print("yeelight-re-gui [--ip IP] [--port PORT]")
            return 0
        else:
            index += 1
    try:
        app = YeelightGui(ip=ip, port=port)
    except Exception as exc:
        try:
            messagebox.showerror("yeelight-re", f"Gagal membuka GUI:\n{exc}")
        except Exception:
            print(f"Gagal membuka GUI: {exc}", file=sys.stderr)
        return 1
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
