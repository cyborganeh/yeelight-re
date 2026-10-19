"""A dependency-free client for the Yeelight LAN protocol."""

from __future__ import annotations

import json
import queue
import socket
import threading
import time
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any, Callable, Iterator, Sequence

from .protocol import (
    CONTROL_PORT,
    DEFAULT_TIMEOUT,
    INT_PROPS,
    STATUS_PROPS,
    CommandError,
    LanControlDisabled,
    ProtocolError,
    YeelightError,
    YeelightTimeout,
    clamp,
    format_command,
    parse_message,
)

NotificationCallback = Callable[[dict[str, Any]], None]


class YeelightClient:
    """Persistent TCP connection to one bulb.

    A background reader dispatches responses to the waiting request and pushes
    ``props`` notifications into a queue. The bulb allows at most four
    simultaneous TCP connections, so reuse one client instead of reconnecting
    for every command when possible.
    """

    def __init__(self, host: str, port: int = CONTROL_PORT, timeout: float = DEFAULT_TIMEOUT):
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)

        self._sock: socket.socket | None = None
        self._reader: threading.Thread | None = None
        self._lock = threading.RLock()
        self._send_lock = threading.Lock()
        self._id = 0
        self._pending: dict[int, Future] = {}
        self._closed = threading.Event()
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._listeners: list[NotificationCallback] = []
        self._reader_error: str | None = None

    # ------------------------------------------------------------------ socket

    def connect(self) -> "YeelightClient":
        with self._lock:
            if self._sock is not None:
                return self
            try:
                sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
            except ConnectionRefusedError as exc:
                raise LanControlDisabled(
                    f"{self.host}:{self.port} refused the connection. "
                    "Enable LAN Control / Developer Mode in the Yeelight app first."
                ) from exc
            except TimeoutError as exc:
                raise YeelightTimeout(
                    f"timed out connecting to {self.host}:{self.port}"
                ) from exc
            except OSError as exc:
                raise YeelightError(f"cannot connect to {self.host}:{self.port}: {exc}") from exc

            sock.settimeout(None)
            try:
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
            self._sock = sock
            self._reader_error = None
            self._closed.clear()
            self._reader = threading.Thread(
                target=self._read_loop,
                args=(sock,),
                name=f"yeelight-reader-{self.host}",
                daemon=True,
            )
            self._reader.start()
        return self

    def _read_loop(self, sock: socket.socket) -> None:
        buffer = b""
        try:
            while not self._closed.is_set():
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    line = line.strip()
                    if line:
                        self._handle_line(line)
        except OSError as exc:
            self._reader_error = str(exc)
        finally:
            self._handle_disconnect(sock)
            try:
                sock.close()
            except OSError:
                pass

    def _handle_line(self, line: bytes) -> None:
        try:
            message = parse_message(line)
        except ProtocolError:
            return

        message_id = message.get("id")
        if message_id is not None:
            try:
                key = int(message_id)
            except (TypeError, ValueError):
                return
            with self._lock:
                future = self._pending.pop(key, None)
            if future is None or future.done():
                return
            if "error" in message:
                error = message.get("error") or {}
                future.set_exception(
                    CommandError(
                        int(error.get("code", -1)),
                        str(error.get("message", "unknown error")),
                    )
                )
            else:
                result = message.get("result", [])
                future.set_result(result)
            return

        if message.get("method") == "props":
            props = message.get("params") or {}
            if not isinstance(props, dict):
                return
            snapshot = dict(props)
            self._queue.put(snapshot)
            for callback in list(self._listeners):
                try:
                    callback(snapshot)
                except Exception:
                    # A user callback must never kill the reader thread.
                    pass

    def _handle_disconnect(self, sock: socket.socket) -> None:
        with self._lock:
            if self._sock is not sock:
                return
            self._sock = None
            pending = list(self._pending.values())
            self._pending.clear()
        for future in pending:
            if not future.done():
                future.set_exception(YeelightError("connection closed by the bulb"))

    def close(self) -> None:
        with self._lock:
            self._closed.set()
            sock = self._sock
            self._sock = None
            reader = self._reader
            self._reader = None
            pending = list(self._pending.values())
            self._pending.clear()
        for future in pending:
            if not future.done():
                future.set_exception(YeelightError("client closed"))
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=2.0)

    def __enter__(self) -> "YeelightClient":
        return self.connect()

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._sock is not None

    # ----------------------------------------------------------------- request

    def send(
        self,
        method: str,
        params: Sequence[Any] | None = None,
        timeout: float | None = None,
    ) -> list[Any]:
        """Send one command and wait for its result array."""
        self.connect()
        with self._send_lock:
            with self._lock:
                if self._sock is None:
                    raise YeelightError("not connected")
                self._id += 1
                message_id = self._id
                future: Future = Future()
                self._pending[message_id] = future
                payload = format_command(message_id, method, params)
                sock = self._sock
            try:
                sock.sendall(payload)
            except OSError as exc:
                with self._lock:
                    self._pending.pop(message_id, None)
                self.close()
                raise YeelightError(f"send failed: {exc}") from exc

        try:
            return future.result(timeout=self.timeout if timeout is None else timeout)
        except FutureTimeout as exc:
            with self._lock:
                self._pending.pop(message_id, None)
            raise YeelightTimeout(
                f"{method}: no response within {self.timeout if timeout is None else timeout}s"
            ) from exc

    def raw(self, method: str, params: Sequence[Any] | None = None) -> list[Any]:
        """Alias for :meth:`send`, used by the CLI ``raw`` command."""
        return self.send(method, params)

    # ---------------------------------------------------------------- commands

    def get_props(self, keys: Sequence[str] | None = None) -> dict[str, Any]:
        keys = list(keys or STATUS_PROPS)
        result = self.send("get_prop", keys)
        if not isinstance(result, list):
            raise ProtocolError("get_prop did not return an array")
        return {key: (result[index] if index < len(result) else "") for index, key in enumerate(keys)}

    def status(self) -> dict[str, Any]:
        props = self.get_props()
        parsed: dict[str, Any] = {}
        for key, value in props.items():
            if key in INT_PROPS:
                try:
                    parsed[key] = int(value)
                except (TypeError, ValueError):
                    parsed[key] = None
            else:
                parsed[key] = value
        return parsed

    def set_power(
        self,
        on: bool,
        effect: str = "smooth",
        duration: int = 300,
        mode: int | None = None,
    ) -> list[Any]:
        params: list[Any] = ["on" if on else "off", effect, int(duration)]
        if mode is not None:
            params.append(int(mode))
        return self.send("set_power", params)

    def toggle(self) -> list[Any]:
        return self.send("toggle")

    def set_bright(self, brightness: int, effect: str = "smooth", duration: int = 300) -> list[Any]:
        return self.send("set_bright", [clamp(brightness, 1, 100), effect, int(duration)])

    def set_rgb(self, rgb: int, effect: str = "smooth", duration: int = 300) -> list[Any]:
        return self.send("set_rgb", [clamp(rgb, 0, 0xFFFFFF), effect, int(duration)])

    def set_ct(self, kelvin: int, effect: str = "smooth", duration: int = 300) -> list[Any]:
        return self.send("set_ct_abx", [clamp(kelvin, 1700, 6500), effect, int(duration)])

    def set_hsv(
        self,
        hue: int,
        sat: int,
        effect: str = "smooth",
        duration: int = 300,
    ) -> list[Any]:
        return self.send("set_hsv", [clamp(hue, 0, 359), clamp(sat, 0, 100), effect, int(duration)])

    def set_scene(self, scene: str, *params: Any) -> list[Any]:
        return self.send("set_scene", [scene, *params])

    def set_name(self, name: str) -> list[Any]:
        return self.send("set_name", [str(name)])

    def start_flow(self, count: int, action: int, expression: str) -> list[Any]:
        return self.send("start_cf", [int(count), int(action), expression])

    def stop_flow(self) -> list[Any]:
        return self.send("stop_cf")

    def set_music(self, enable: bool, host: str = "", port: int = 0) -> list[Any]:
        if enable:
            return self.send("set_music", [1, host, int(port)])
        return self.send("set_music", [0])

    # ----------------------------------------------------------- notifications

    def add_listener(self, callback: NotificationCallback) -> None:
        self._listeners.append(callback)

    def remove_listener(self, callback: NotificationCallback) -> None:
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass

    def get_notification(self, timeout: float | None = 1.0) -> dict[str, Any] | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def iter_notifications(self, timeout: float | None = None) -> Iterator[dict[str, Any]]:
        """Yield ``props`` notifications until ``timeout`` seconds elapse.

        With ``timeout=None`` this keeps waiting until the caller stops iterating
        or the connection closes.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            wait = 0.5
            if deadline is not None:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return
                wait = min(wait, remaining)
            try:
                yield self._queue.get(timeout=wait)
            except queue.Empty:
                if self._closed.is_set():
                    return

    def local_address(self) -> str:
        """Local IP that the bulb should send music-mode UDP packets to."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((self.host, self.port))
            return sock.getsockname()[0]
        finally:
            sock.close()


class MusicMode:
    """Context manager for the bulb's low-latency "music mode".

    Entering the mode tells the bulb to stream state changes over UDP to us. In
    return the 60 commands/minute quota is lifted, which makes smooth colour
    fades and audio visualisations possible.
    """

    def __init__(
        self,
        client: YeelightClient,
        bind_ip: str = "0.0.0.0",
        udp_port: int = 0,
    ):
        self.client = client
        self._bind_ip = bind_ip
        self._requested_port = int(udp_port)
        self._sock: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self.port = 0
        self.local_ip = ""

    def __enter__(self) -> "MusicMode":
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            self._sock.bind((self._bind_ip, self._requested_port))
            self._sock.settimeout(0.5)
            self.port = self._sock.getsockname()[1]
            self.local_ip = self.client.local_address()
            self.client.set_music(True, self.local_ip, self.port)
        except Exception:
            self._sock.close()
            self._sock = None
            raise
        self._thread = threading.Thread(
            target=self._recv_loop,
            args=(self._sock,),
            name="yeelight-music-udp",
            daemon=True,
        )
        self._thread.start()
        return self

    def _recv_loop(self, sock: socket.socket) -> None:
        while not self._stop.is_set():
            try:
                payload, _address = sock.recvfrom(65535)
            except TimeoutError:
                continue
            except OSError:
                return
            try:
                message = parse_message(payload)
            except ProtocolError:
                continue
            if message.get("method") == "props" and isinstance(message.get("params"), dict):
                self._queue.put(dict(message["params"]))

    def get(self, timeout: float | None = 1.0) -> dict[str, Any] | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def __exit__(self, exc_type, exc, traceback) -> None:
        self._stop.set()
        try:
            self.client.set_music(False)
        except YeelightError:
            pass
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        if self._thread is not None and self._thread is not threading.current_thread():
            self._thread.join(timeout=2.0)
        self._sock = None
        self._thread = None


def parse_json_argument(text: str) -> list[Any]:
    """Parse a JSON array given on the command line."""
    value = json.loads(text)
    if not isinstance(value, list):
        raise ValueError("params must be a JSON array")
    return value
