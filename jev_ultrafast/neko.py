"""Neko sandbox mode (MVP-5): an isolated browser the agent can work in.

Spec §10: the sidebar offers "use my current browser" vs "open isolated
browser". The isolated target is a self-hosted Neko container (Docker +
WebRTC): the user can watch it at the web URL while the agent drives the
browser inside it over CDP, with the same observe/act/fresh contract as the
live-tab and Chrome paths.

Stock Neko images do not publish a CDP endpoint, so the manager passes the
remote-debugging flags through the image's browser-args env when the image
supports them and *probes* the CDP port before declaring a session drivable.
A session whose CDP port never answers is reported as "manual": the isolated
browser is up for watching, but the agent cannot drive it, and the sidebar
says exactly that instead of failing mid-mission.
"""

import base64
import hashlib
import json
import os
import secrets
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from .browser import MARKER, READ_STATE, StalePage, fingerprint, guard_expression, target_expression

SESSIONS_PATH = Path(os.environ.get("JEV_NEKO_SESSIONS", "artifacts/neko-sessions.json"))
DEFAULT_IMAGE = os.environ.get("NEKO_IMAGE", "ghcr.io/m1k1o/neko/chromium:latest")
READY_TIMEOUT = float(os.environ.get("NEKO_READY_TIMEOUT", "45"))


class NekoUnavailable(RuntimeError):
    """Docker is missing, or the container never became ready."""


# ── docker seam ───────────────────────────────────────────────────────────────


class DockerRunner:
    """Thin subprocess wrapper; tests inject a fake with the same interface."""

    def run(self, argv):
        completed = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        if completed.returncode != 0:
            raise NekoUnavailable((completed.stderr or completed.stdout or "docker failed").strip()[:300])
        return completed.stdout.strip()

    def version(self):
        try:
            self.run(["docker", "version", "--format", "{{.Server.Version}}"])
            return True
        except (NekoUnavailable, OSError, subprocess.TimeoutExpired):
            return False


def _http_json(url, timeout=3):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - loopback only
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None


class NekoSessionManager:
    """Starts, tracks and stops isolated Neko browser sessions."""

    def __init__(self, runner=None, probe=None, registry_path=None, on_event=None):
        self.runner = runner or DockerRunner()
        self.probe = probe or _http_json  # (url) -> parsed json or None
        self.registry_path = Path(registry_path) if registry_path else SESSIONS_PATH
        self.on_event = on_event or (lambda **_kwargs: None)

    # ── registry ──

    def _load(self):
        try:
            data = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _save(self, data):
        try:
            self.registry_path.parent.mkdir(parents=True, exist_ok=True)
            self.registry_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except OSError:
            pass

    def list(self):
        return list((self._load().get("sessions") or {}).values())

    def current(self):
        sessions = self._load().get("sessions") or {}
        for session in sessions.values():
            if session.get("state") == "running":
                return session
        return None

    def _set(self, session):
        data = self._load()
        data.setdefault("sessions", {})[session["id"]] = session
        self._save(data)

    def _drop(self, session_id):
        data = self._load()
        (data.get("sessions") or {}).pop(session_id, None)
        self._save(data)

    # ── lifecycle ──

    def available(self):
        return self.runner.version()

    def start(self, web_port=None, cdp_port=None, image=None, password=None):
        if not self.available():
            raise NekoUnavailable("Docker is not available; install Docker to use the isolated browser.")
        existing = self.current()
        if existing:
            return existing
        session_id = secrets.token_hex(4)
        web_port = int(web_port or os.environ.get("NEKO_WEB_PORT", "8088"))
        cdp_port = int(cdp_port or os.environ.get("NEKO_CDP_PORT", "9223"))
        image = image or DEFAULT_IMAGE
        password = password or os.environ.get("NEKO_PASSWORD") or secrets.token_hex(6)
        browser_args = os.environ.get(
            "NEKO_BROWSER_ARGS", "--remote-debugging-port=9222 --remote-debugging-address=0.0.0.0"
        )
        name = f"jev-neko-{session_id}"
        argv = [
            "docker", "run", "-d", "--name", name, "--shm-size", "2g",
            "-p", f"127.0.0.1:{web_port}:8080",
            "-p", f"127.0.0.1:{cdp_port}:9222",
            "-e", f"NEKO_PASSWORD_ADMIN={password}",
            "-e", f"NEKO_PASSWORD_USER={password}",
            "-e", f"NEKO_BROWSER_ARGS={browser_args}",
            image,
        ]
        container = self.runner.run(argv)
        session = {
            "id": session_id,
            "container": container or name,
            "name": name,
            "image": image,
            "webUrl": f"http://127.0.0.1:{web_port}",
            "cdpUrl": f"http://127.0.0.1:{cdp_port}",
            "startedAt": time.time(),
            "state": "starting",
        }
        self._set(session)
        self.on_event(tool="sandbox", args=json.dumps({"action": "start", "session": session_id}),
                      ok=True, preview=f"neko container {name}")
        # The agent needs CDP; the user needs the WebRTC page. Only a drivable
        # session ends the wait early — a web-only container is reported as
        # "manual" rather than pretending the agent can work in it.
        deadline = time.monotonic() + READY_TIMEOUT
        web_ok = cdp_ok = False
        while time.monotonic() < deadline:
            web_ok = web_ok or self._tcp_open(web_port)
            cdp_ok = isinstance(self.probe(f"{session['cdpUrl']}/json/version"), dict)
            if cdp_ok:
                break
            time.sleep(0.25)
        web_ok = web_ok or self._tcp_open(web_port)
        session["state"] = "running" if cdp_ok else "manual"
        session["webReady"] = bool(web_ok)
        session["cdpReady"] = bool(cdp_ok)
        if not web_ok and not cdp_ok:
            self.stop(session_id)
            raise NekoUnavailable(
                f"The Neko container started but never answered on ports {web_port}/{cdp_port}. "
                "Check the image (NEKO_IMAGE) and that the ports are free."
            )
        self._set(session)
        return session

    def _tcp_open(self, port):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            return False

    def stop(self, session_id):
        data = self._load()
        session = (data.get("sessions") or {}).get(session_id)
        if not session:
            return False
        try:
            self.runner.run(["docker", "rm", "-f", session.get("name") or f"jev-neko-{session_id}"])
        except (NekoUnavailable, OSError, subprocess.TimeoutExpired):
            pass  # a gone container is a stopped container
        self._drop(session_id)
        self.on_event(tool="sandbox", args=json.dumps({"action": "stop", "session": session_id}),
                      ok=True, preview=f"neko container {session.get('name')}")
        return True

    def stop_all(self):
        stopped = [session["id"] for session in self.list()]
        for session_id in stopped:
            self.stop(session_id)
        return stopped


# ── minimal CDP client (stdlib only) ──────────────────────────────────────────

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def _read_exact(sock, count):
    data = b""
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise ConnectionError("Connection closed")
        data += chunk
    return data


def _read_frame(sock):
    head = _read_exact(sock, 2)
    opcode = head[0] & 0x0F
    masked = bool(head[1] & 0x80)
    length = head[1] & 0x7F
    if length == 126:
        length = struct.unpack(">H", _read_exact(sock, 2))[0]
    elif length == 127:
        length = struct.unpack(">Q", _read_exact(sock, 8))[0]
    mask = _read_exact(sock, 4) if masked else None
    payload = _read_exact(sock, length)
    if mask:
        payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
    return opcode, payload


def _send_frame(sock, payload, opcode=1):
    head = bytes([0x80 | opcode])
    length = len(payload)
    if length < 126:
        head += bytes([length])
    elif length < 65536:
        head += bytes([126]) + struct.pack(">H", length)
    else:
        head += bytes([127]) + struct.pack(">Q", length)
    sock.sendall(head + payload)


class CDPClient:
    """A WebSocket CDP client: request/response by id, events ignored."""

    def __init__(self, http_url, transport=None):
        self._transport = transport
        self._sock = None
        self._lock = threading.Lock()
        self._pending = {}
        self._next_id = 1
        if transport is None:
            version = _http_json(http_url.rstrip("/") + "/json/version")
            if not isinstance(version, dict) or not version.get("webSocketDebuggerUrl"):
                raise NekoUnavailable(f"No CDP endpoint at {http_url} (is the sandbox browser drivable?)")
            self._connect(version["webSocketDebuggerUrl"])

    def _connect(self, ws_url):
        parsed = urllib.parse.urlparse(ws_url)
        sock = socket.create_connection((parsed.hostname, parsed.port or 80), timeout=10)
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        sock.sendall(
            (
                f"GET {parsed.path or '/'} HTTP/1.1\r\nHost: {parsed.hostname}:{parsed.port or 80}\r\n"
                f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode()
        )
        status = b""
        while b"\r\n\r\n" not in status:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError("Closed during CDP handshake")
            status += chunk
        if b" 101 " not in status.split(b"\r\n")[0]:
            first_line = status.split(b"\r\n")[0].decode(errors="replace")
            raise ConnectionError(f"CDP handshake rejected: {first_line}")
        accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
        if accept.encode() not in status:
            raise ConnectionError("CDP handshake: bad Sec-WebSocket-Accept")
        self._sock = sock
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        while True:
            try:
                opcode, payload = _read_frame(self._sock)
            except (ConnectionError, OSError):
                return
            if opcode == 8:
                return
            if opcode != 1:
                continue
            try:
                message = json.loads(payload.decode("utf-8"))
            except ValueError:
                continue
            message_id = message.get("id")
            if message_id is None:
                continue  # events are not needed by the agent loop
            entry = self._pending.pop(message_id, None)
            if entry:
                entry["result"] = message
                entry["event"].set()

    def call(self, method, timeout=30, **params):
        if self._transport is not None:
            return self._transport(method, params)
        with self._lock:
            message_id = self._next_id
            self._next_id += 1
            entry = {"event": threading.Event()}
            self._pending[message_id] = entry
            mask = os.urandom(4)
            payload = json.dumps({"id": message_id, "method": method, "params": params}).encode("utf-8")
            header = bytes([0x81])
            length = len(payload)
            if length < 126:
                header += bytes([0x80 | length])
            elif length < 65536:
                header += bytes([0x80 | 126]) + struct.pack(">H", length)
            else:
                header += bytes([0x80 | 127]) + struct.pack(">Q", length)
            masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
            self._sock.sendall(header + mask + masked)
        if not entry["event"].wait(timeout):
            raise RuntimeError(f"CDP call {method} timed out")
        message = entry["result"]
        if message.get("error"):
            raise RuntimeError(f"CDP {method}: {message['error'].get('message', message['error'])}")
        return message.get("result") or {}

    def close(self):
        try:
            if self._sock is not None:
                _send_frame(self._sock, b"", opcode=8)
                self._sock.close()
        except OSError:
            pass
        self._sock = None


# ── the sandbox browser driver ────────────────────────────────────────────────


class SandboxBrowser:
    """Drives the browser inside a Neko session; same contract as Browser."""

    def __init__(self, url, cdp_url=None, transport=None):
        self.client = CDPClient(cdp_url or "", transport=transport)
        self.created_target = None
        targets = self.client.call("Target.getTargets").get("targetInfos") or []
        page = next((t for t in targets if t.get("type") == "page"), None)
        if page is None:
            self.created_target = self.client.call("Target.createTarget", url="about:blank")["targetId"]
            target_id = self.created_target
        else:
            target_id = page["targetId"]
        self.session = self.client.call("Target.attachToTarget", targetId=target_id, flatten=True)["sessionId"]
        self.call("Emulation.setDeviceMetricsOverride", width=1120, height=780, deviceScaleFactor=1, mobile=False)
        self.call("Emulation.setFocusEmulationEnabled", enabled=True)
        self.call("Page.navigate", url=url)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.evaluate("document.readyState") == "complete":
                break
            time.sleep(0.02)

    def call(self, method, **params):
        return self.client.call(method, **params)

    def evaluate(self, expression):
        response = self.call("Runtime.evaluate", expression=expression, returnByValue=True)
        if response.get("exceptionDetails"):
            raise StalePage("Document changed during evaluation")
        return response.get("result", {}).get("value")

    def observe(self, screenshot=True):
        for attempt in range(10):
            try:
                info = self.evaluate(READ_STATE)
                break
            except StalePage:
                if attempt == 9:
                    raise
                time.sleep(0.02)
        if info is None:
            raise StalePage("Document is navigating")
        info["fingerprint"] = fingerprint(info)
        if screenshot:
            info["screenshot"] = self.call("Page.captureScreenshot", format="jpeg", quality=72)["data"]
        return info

    def fresh(self, page, action=None):
        if action is not None and action["kind"] in {"click", "select"}:
            node = action["node"]
            if type(node) is not int:
                return False
            current = self.evaluate(guard_expression(node))
            return current == [page["page_key"], page["guards"].get(str(node))]
        return self.evaluate(MARKER) == page["marker"]

    def act(self, action, page, text=None):
        if not self.fresh(page, action):
            raise StalePage("Page changed since this decision. Observe again.")
        if action["kind"] == "wait":
            time.sleep(0.1)
            return {"executed": action["id"]}
        kind = action["kind"]
        if kind == "scroll":
            self.call("Input.dispatchMouseEvent", type="mouseWheel", x=550, y=650, deltaX=0, deltaY=action["delta"])
            return {"executed": action["id"]}
        target = self.evaluate(target_expression(action))
        if target is None:
            if kind == "select":
                raise RuntimeError("Dropdown execution was not confirmed; inspect before retrying.")
            raise StalePage("Target changed or is covered. Observe again.")
        if kind != "select":
            x, y = target["x"], target["y"]
            for event in ("mousePressed", "mouseReleased"):
                self.call("Input.dispatchMouseEvent", type=event, x=x, y=y, button="left", clickCount=1)
            if kind == "fill":
                modifiers = 4 if sys.platform == "darwin" else 2
                for event_type in ("keyDown", "keyUp"):
                    self.call(
                        "Input.dispatchKeyEvent",
                        type=event_type, key="a", code="KeyA", modifiers=modifiers,
                        **({"commands": ["selectAll"]} if event_type == "keyDown" else {}),
                    )
                self.call("Input.insertText", text=text)
        return {"executed": action["id"]}

    def close(self):
        if self.created_target:
            try:
                self.client.call("Target.closeTarget", targetId=self.created_target)
            except RuntimeError:
                pass
            self.created_target = None
        self.client.close()
