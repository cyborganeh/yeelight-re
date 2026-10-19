"""A dependency-free local dashboard for one bulb.

Bind to 127.0.0.1 by default. There is no authentication: this is a LAN control
panel, not an internet service.
"""

from __future__ import annotations

import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from .client import YeelightClient
from .presets import FLOW_PRESETS, SCENES
from .protocol import YeelightError

ALLOWED_METHODS = {
    "set_power",
    "toggle",
    "set_bright",
    "set_rgb",
    "set_ct_abx",
    "set_hsv",
    "set_scene",
    "set_name",
    "start_cf",
    "stop_cf",
    "set_adjust",
    "adjust_bright",
    "adjust_ct",
    "adjust_color",
}


class _Handler(BaseHTTPRequestHandler):
    server_version = "YeelightLocal/0.1"

    @property
    def bulb(self) -> YeelightClient:
        return self.server.bulb  # type: ignore[attr-defined]

    @property
    def lock(self) -> threading.Lock:
        return self.server.lock  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:
        # Keep the console clean; errors are still visible.
        return

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _html(self, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (stdlib naming)
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._html(INDEX_HTML)
            return
        if path == "/api/state":
            try:
                with self.lock:
                    status = self.bulb.status()
            except YeelightError as exc:
                self._json({"ok": False, "error": str(exc)}, 503)
                return
            self._json({"ok": True, **status})
            return
        if path == "/api/presets":
            self._json(
                {
                    "scenes": {name: list(params) for name, params in SCENES.items()},
                    "flows": {
                        name: {"count": count, "action": action, "expression": expression}
                        for name, (count, action, expression) in FLOW_PRESETS.items()
                    },
                }
            )
            return
        if path == "/api/health":
            self._json({"ok": True, "host": self.bulb.host})
            return
        self._json({"ok": False, "error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/cmd":
            self._json({"ok": False, "error": "not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 65536:
                raise ValueError("invalid body length")
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            method = str(payload["method"])
            params = payload.get("params", [])
            if method not in ALLOWED_METHODS:
                raise ValueError(f"method not allowed: {method}")
            if not isinstance(params, list) or len(params) > 16:
                raise ValueError("params must be an array of at most 16 values")
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            self._json({"ok": False, "error": str(exc)}, 400)
            return

        try:
            with self.lock:
                result = self.bulb.send(method, params)
        except YeelightError as exc:
            self._json({"ok": False, "error": str(exc)}, 502)
            return
        self._json({"ok": True, "result": result})


def make_server(
    client: YeelightClient,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), _Handler)
    server.bulb = client  # type: ignore[attr-defined]
    server.lock = threading.Lock()  # type: ignore[attr-defined]
    server.daemon_threads = True
    return server


def serve(client: YeelightClient, host: str = "127.0.0.1", port: int = 8765) -> None:
    server = make_server(client, host, port)
    try:
        server.serve_forever(poll_interval=0.25)
    finally:
        server.server_close()


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Yeelight Local</title>
<style>
  :root {
    --bg: #080b10;
    --card: rgba(20, 25, 35, .82);
    --line: rgba(255, 255, 255, .09);
    --text: #eef2f7;
    --muted: #8b95a7;
    --accent: #ffb84d;
    --accent-2: #7dd3fc;
    --danger: #ff6b6b;
  }
  * { box-sizing: border-box; }
  html, body { min-height: 100%; }
  body {
    margin: 0;
    padding: 32px 16px;
    display: flex;
    justify-content: center;
    align-items: flex-start;
    color: var(--text);
    background:
      radial-gradient(900px 500px at 15% -10%, rgba(255, 184, 77, .14), transparent 60%),
      radial-gradient(800px 500px at 110% 20%, rgba(125, 211, 252, .12), transparent 55%),
      var(--bg);
    font: 15px/1.5 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  .shell { width: min(100%, 520px); }
  .card {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 26px;
    padding: 24px;
    box-shadow: 0 30px 80px rgba(0, 0, 0, .5);
    backdrop-filter: blur(18px);
  }
  .top { display: flex; justify-content: space-between; gap: 16px; align-items: flex-start; }
  .eyebrow { color: var(--muted); font-size: 11px; letter-spacing: .18em; text-transform: uppercase; }
  h1 { font-size: 26px; line-height: 1.15; margin: 6px 0 0; letter-spacing: -.02em; }
  .status {
    display: inline-flex; align-items: center; gap: 7px; white-space: nowrap;
    color: var(--muted); font-size: 12px; border: 1px solid var(--line);
    padding: 7px 10px; border-radius: 999px; background: rgba(0, 0, 0, .2);
  }
  .dot { width: 7px; height: 7px; border-radius: 50%; background: #64748b; }
  .status.online .dot { background: #4ade80; box-shadow: 0 0 12px #4ade80; }
  .status.online { color: #c7f9d8; }
  .power-row { display: flex; align-items: center; gap: 18px; margin: 26px 0 8px; }
  .power {
    width: 84px; height: 84px; border-radius: 50%; border: 1px solid var(--line);
    background: radial-gradient(circle at 30% 20%, #2a3140, #10141c);
    color: #6b7382; display: grid; place-items: center; cursor: pointer;
    transition: transform .15s ease, color .2s, box-shadow .2s, background .2s;
    flex: 0 0 auto;
  }
  .power:hover { transform: translateY(-1px); }
  .power:active { transform: scale(.97); }
  .power.on {
    color: #1b1300; background: radial-gradient(circle at 30% 20%, #ffe2a8, var(--accent));
    box-shadow: 0 0 45px rgba(255, 184, 77, .35);
  }
  .power svg { width: 30px; height: 30px; }
  .power-copy .label { font-size: 11px; letter-spacing: .16em; text-transform: uppercase; color: var(--muted); }
  .power-copy .value { font-size: 22px; font-weight: 650; margin-top: 2px; }
  .power-copy .hint { color: var(--muted); font-size: 12px; margin-top: 3px; }
  .block { border-top: 1px solid var(--line); margin-top: 22px; padding-top: 18px; }
  .row { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; margin-bottom: 10px; }
  .row label { font-size: 12px; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); }
  .row output { font-variant-numeric: tabular-nums; font-size: 14px; color: #dbe4f0; }
  input[type=range] {
    -webkit-appearance: none; appearance: none; width: 100%; height: 26px; background: transparent; margin: 0;
  }
  input[type=range]::-webkit-slider-runnable-track {
    height: 7px; border-radius: 99px; background: rgba(255,255,255,.12);
  }
  input[type=range]::-moz-range-track { height: 7px; border-radius: 99px; background: rgba(255,255,255,.12); }
  input[type=range]::-webkit-slider-thumb {
    -webkit-appearance: none; width: 22px; height: 22px; margin-top: -7.5px; border-radius: 50%;
    background: #f4f7fb; border: 4px solid #1a202c; box-shadow: 0 2px 10px rgba(0,0,0,.5); cursor: grab;
  }
  input[type=range]::-moz-range-thumb {
    width: 16px; height: 16px; border-radius: 50%; background: #f4f7fb; border: 4px solid #1a202c;
    box-shadow: 0 2px 10px rgba(0,0,0,.5); cursor: grab;
  }
  #ct { border-radius: 99px; }
  .color-grid { display: grid; grid-template-columns: 58px 1fr; gap: 14px; align-items: center; }
  input[type=color] {
    width: 58px; height: 58px; padding: 0; border: 1px solid var(--line); border-radius: 16px;
    background: transparent; cursor: pointer;
  }
  input[type=color]::-webkit-color-swatch-wrapper { padding: 4px; }
  input[type=color]::-webkit-color-swatch { border: 0; border-radius: 12px; }
  input[type=color]::-moz-color-swatch { border: 0; border-radius: 12px; }
  .swatches { display: grid; grid-template-columns: repeat(8, 1fr); gap: 7px; }
  .swatch {
    aspect-ratio: 1; border-radius: 9px; border: 1px solid rgba(255,255,255,.16); cursor: pointer;
    transition: transform .12s ease;
  }
  .swatch:hover { transform: translateY(-2px); }
  .chips { display: flex; flex-wrap: wrap; gap: 8px; }
  .chip {
    border: 1px solid var(--line); background: rgba(255,255,255,.04); color: #dbe4f0;
    padding: 8px 12px; border-radius: 999px; cursor: pointer; font: inherit; font-size: 13px;
    transition: background .15s, border-color .15s;
  }
  .chip:hover { background: rgba(255,255,255,.09); border-color: rgba(255,255,255,.2); }
  .chip.active { background: rgba(255,184,77,.16); border-color: rgba(255,184,77,.5); color: #ffe1ad; }
  .foot { color: var(--muted); font-size: 11px; text-align: center; margin-top: 16px; letter-spacing: .04em; }
  .toast {
    position: fixed; left: 50%; bottom: 24px; transform: translate(-50%, 20px);
    background: #2b1114; color: #ffd7d7; border: 1px solid rgba(255,107,107,.4);
    padding: 10px 14px; border-radius: 10px; opacity: 0; pointer-events: none;
    transition: opacity .2s, transform .2s; max-width: min(90vw, 480px); font-size: 13px;
  }
  .toast.show { opacity: 1; transform: translate(-50%, 0); }
  .loading { opacity: .55; }
  @media (max-width: 420px) {
    .card { padding: 20px; border-radius: 22px; }
    h1 { font-size: 22px; }
    .swatches { grid-template-columns: repeat(4, 1fr); }
  }
</style>
</head>
<body>
<div class="shell">
  <main class="card" id="card">
    <div class="top">
      <div>
        <div class="eyebrow">Local control &middot; YLDP06YL</div>
        <h1 id="name">Yeelight</h1>
      </div>
      <div class="status" id="status"><span class="dot"></span><span id="statusText">connecting</span></div>
    </div>

    <div class="power-row">
      <button class="power" id="power" title="Power" aria-label="Toggle power">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
          <path d="M12 3v9"/><path d="M6.2 6.2a8 8 0 1 0 11.6 0"/>
        </svg>
      </button>
      <div class="power-copy">
        <div class="label">Power</div>
        <div class="value" id="powerText">--</div>
        <div class="hint" id="modeText">waiting for bulb</div>
      </div>
    </div>

    <section class="block">
      <div class="row"><label for="bright">Brightness</label><output id="brightOut">--</output></div>
      <input type="range" id="bright" min="1" max="100" step="1" value="100">
    </section>

    <section class="block">
      <div class="row"><label for="color">Colour</label><output id="colorOut">--</output></div>
      <div class="color-grid">
        <input type="color" id="color" value="#ffffff">
        <div class="swatches" id="swatches"></div>
      </div>
    </section>

    <section class="block">
      <div class="row"><label for="ct">White temperature</label><output id="ctOut">--</output></div>
      <input type="range" id="ct" min="1700" max="6500" step="100" value="4000">
    </section>

    <section class="block">
      <div class="row"><label>Scenes</label><output id="flowOut"></output></div>
      <div class="chips" id="scenes"></div>
      <div class="chips" id="flows" style="margin-top:8px"></div>
    </section>
  </main>
  <div class="foot">direct TCP 55443 &middot; no account &middot; no cloud</div>
</div>
<div class="toast" id="toast"></div>

<script>
const COLORS = ["#ff3b30","#ff9500","#ffcc00","#34c759","#00c7be","#0a84ff","#5e5ce6","#ff2d95"];
const $ = (id) => document.getElementById(id);
let state = {};
let dragging = false;
let inFlight = false;
let colorTimer = null;
let ctTimer = null;

function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.classList.add("show");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("show"), 4200);
}

async function request(path, options) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || ("HTTP " + response.status));
  }
  return data;
}

async function refresh() {
  if (dragging || inFlight) return;
  try {
    const data = await request("/api/state");
    state = data;
    render();
  } catch (error) {
    $("status").classList.remove("online");
    $("statusText").textContent = "offline";
    $("modeText").textContent = error.message;
  }
}

function render() {
  const on = state.power === "on";
  $("power").classList.toggle("on", on);
  $("powerText").textContent = on ? "On" : "Off";
  $("name").textContent = state.name || "Yeelight";
  $("status").classList.add("online");
  $("statusText").textContent = "LAN · " + (state.music_on === 1 ? "music" : "ready");
  const modes = {0: "normal", 1: "white", 2: "colour", 3: "HSV"};
  $("modeText").textContent = modes[state.color_mode] || "ready";

  if (!dragging) {
    $("bright").value = state.bright || 1;
    $("brightOut").textContent = (state.bright || 0) + "%";
    $("ct").value = state.ct || 4000;
    $("ctOut").textContent = (state.ct || 0) + " K";
  }
  if (typeof state.rgb === "number") {
    const hex = "#" + state.rgb.toString(16).padStart(6, "0");
    $("color").value = hex;
    $("colorOut").textContent = hex.toUpperCase();
  }
  $("flowOut").textContent = state.flowing === 1 ? "flow running" : "";
}

async function command(method, params) {
  if (inFlight) return;
  inFlight = true;
  $("card").classList.add("loading");
  try {
    await request("/api/cmd", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({method, params})
    });
    inFlight = false;
    await refresh();
  } catch (error) {
    toast(error.message);
  } finally {
    inFlight = false;
    $("card").classList.remove("loading");
  }
}

$("power").onclick = () => command("set_power", [state.power === "on" ? "off" : "on", "smooth", 300]);

$("bright").addEventListener("input", () => {
  $("brightOut").textContent = $("bright").value + "%";
});
$("bright").addEventListener("pointerdown", () => { dragging = true; });
$("bright").addEventListener("pointerup", () => { dragging = false; });
$("bright").addEventListener("change", () => {
  dragging = false;
  command("set_bright", [parseInt($("bright").value, 10), "smooth", 250]);
});

$("ct").addEventListener("input", () => {
  $("ctOut").textContent = $("ct").value + " K";
});
$("ct").addEventListener("pointerdown", () => { dragging = true; });
$("ct").addEventListener("pointerup", () => { dragging = false; });
$("ct").addEventListener("change", () => {
  dragging = false;
  clearTimeout(ctTimer);
  ctTimer = setTimeout(() => command("set_ct_abx", [parseInt($("ct").value, 10), "smooth", 300]), 60);
});

$("color").addEventListener("input", () => {
  const hex = $("color").value;
  $("colorOut").textContent = hex.toUpperCase();
  clearTimeout(colorTimer);
  colorTimer = setTimeout(() => {
    command("set_rgb", [parseInt(hex.slice(1), 16), "smooth", 200]);
  }, 140);
});

function makeSwatch(hex) {
  const el = document.createElement("button");
  el.className = "swatch";
  el.style.background = hex;
  el.title = hex;
  el.onclick = () => command("set_scene", ["color", parseInt(hex.slice(1), 16), state.bright || 100]);
  return el;
}
COLORS.forEach((hex) => $("swatches").appendChild(makeSwatch(hex)));

async function loadPresets() {
  try {
    const data = await request("/api/presets");
    const scenes = $("scenes");
    Object.entries(data.scenes).forEach(([name, params]) => {
      const button = document.createElement("button");
      button.className = "chip";
      button.textContent = name;
      button.onclick = () => command("set_scene", params);
      scenes.appendChild(button);
    });
    const flows = $("flows");
    Object.entries(data.flows).forEach(([name, flow]) => {
      const button = document.createElement("button");
      button.className = "chip";
      button.textContent = name + " ↻";
      button.onclick = () => {
        if (state.flowing === 1) command("stop_cf", []);
        else command("start_cf", [flow.count, flow.action, flow.expression]);
      };
      flows.appendChild(button);
    });
  } catch (error) {
    toast("Presets unavailable: " + error.message);
  }
}

loadPresets();
refresh();
setInterval(refresh, 2000);
</script>
</body>
</html>
"""
