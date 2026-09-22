"""Firefox extension bridge: a stdlib WebSocket server, a Browser-compatible tab driver, and a task runner.

The extension (see extension/) connects to ws://127.0.0.1:8767 and exposes one live tab.
The host sends observe/act/fresh/open commands; the extension replies with results.
Task runs arrive as "run" messages and drive the normal Agent loop with FirefoxBrowser.
"""

import base64
import hashlib
import json
import os
import secrets
import socket
import struct
import threading
import time

from .browser import StalePage, fingerprint
from .model import policy_description


def check_providers():
    """One tiny real request per configured role; per-role status for the sidebar.

    This is the setup self-test: it shows exactly which model works and, when
    one fails, the provider's own error (wrong key, wrong model id, ...).
    """
    from . import providers as provider_layer

    roles = []
    if any(os.environ.get(name, "").strip() for name in ("PLANNER_PROVIDER", "PLANNER_BASE_URL")):
        roles.append("planner")
    roles.append("policy")
    roles.append("text")
    results = {}
    for role in roles:
        entry = {"role": role, "model": None, "ok": False, "latency_ms": None, "detail": ""}
        try:
            if role == "policy" and os.environ.get("TYPESAFE_API_KEY"):
                entry.update(model="jev-latest (TypeSafe)", ok=True, detail="TypeSafe key configured", latency_ms=0)
            else:
                provider = provider_layer.resolve(role)
                entry["model"] = f"{provider['name']}:{provider['model']}"
                started = time.perf_counter()
                provider_layer.chat(
                    provider,
                    "You are a connectivity check. Reply with exactly the JSON object {} and nothing else.",
                    "ping",
                    max_tokens=512,
                )
                entry.update(ok=True, latency_ms=round((time.perf_counter() - started) * 1000), detail="connected")
        except ValueError as error:
            entry["detail"] = str(error)
            if role == "text" and "API_KEY" in str(error):
                entry["detail"] += " (only needed when the agent types into fields)"
        except RuntimeError as error:
            entry["detail"] = str(error)[:300]
            if "404" in entry["detail"] or "not found" in entry["detail"].lower():
                entry["detail"] += " — check the exact model id in the provider's catalogue"
        results[role] = entry
    return results

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
DEFAULT_PORT = 8767
COMMAND_TIMEOUT = 60.0


class BridgeError(RuntimeError):
    """The extension is unreachable or rejected a command."""


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


class BridgeServer:
    """A single-client WebSocket server bound to loopback; the Firefox extension is the client."""

    def __init__(self, port=0, token=None):
        self.token = token
        self.runner = None
        self._send_lock = threading.Lock()
        self._pending = {}
        self._next_id = 1
        self._client = None
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", port))
        self._sock.listen(1)
        self.port = self._sock.getsockname()[1]

    @property
    def connected(self):
        return self._client is not None

    def close(self):
        try:
            self._sock.close()
        except OSError:
            pass

    def start(self):
        thread = threading.Thread(target=self._accept_loop, daemon=True)
        thread.start()
        return thread

    def _accept_loop(self):
        while True:
            try:
                conn, _address = self._sock.accept()
            except OSError:
                return
            try:
                self._serve(conn)
            except (ConnectionError, OSError, ValueError):
                pass
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
                self._clear_client(conn)

    def _clear_client(self, conn):
        with self._send_lock:
            if self._client is conn:
                self._client = None
        for entry in self._pending.values():
            entry["error"] = "Firefox extension disconnected"
            entry["event"].set()
        self._pending = {}

    def _serve(self, conn):
        headers = self._read_handshake(conn)
        origin = headers.get("origin", "")
        if origin and not origin.startswith("moz-extension://"):
            conn.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n")
            raise ValueError("Forbidden origin")
        accept = base64.b64encode(hashlib.sha1((headers["sec-websocket-key"] + GUID).encode()).digest()).decode()
        conn.sendall(
            (
                "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
            ).encode()
        )
        with self._send_lock:
            self._client = conn
        while True:
            opcode, payload = _read_frame(conn)
            if opcode == 8:
                return
            if opcode == 9:
                with self._send_lock:
                    _send_frame(conn, payload, opcode=10)
                continue
            if opcode != 1:
                continue
            try:
                self._route(json.loads(payload.decode("utf-8")))
            except Exception as error:  # a malformed message must not kill the reader
                self.broadcast({"type": "error", "message": f"Bridge error: {error}"})

    @staticmethod
    def _read_handshake(conn):
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = conn.recv(4096)
            if not chunk:
                raise ConnectionError("Closed during handshake")
            data += chunk
            if len(data) > 16384:
                raise ValueError("Oversized handshake")
        headers = {}
        for line in data.decode("latin-1").split("\r\n\r\n", 1)[0].split("\r\n")[1:]:
            if ":" in line:
                name, value = line.split(":", 1)
                headers[name.strip().lower()] = value.strip()
        if "sec-websocket-key" not in headers:
            raise ValueError("Not a WebSocket handshake")
        return headers

    def _route(self, message):
        if "id" in message and ("ok" in message or "error" in message):
            entry = self._pending.pop(message["id"], None)
            if entry:
                entry["result" if message.get("ok") else "error"] = message.get("result") or message.get("error")
                entry["event"].set()
            return
        kind = message.get("type")
        if kind == "hello":
            if self.token and not secrets.compare_digest(message.get("token", ""), self.token):
                self.send({"type": "welcome", "ok": False, "error": "Invalid bridge token"})
                return
            self.send({"type": "welcome", "ok": True, "state": self.runner.current_state() if self.runner else None})
            if self.runner:
                threading.Thread(target=self.runner.run_provider_check, daemon=True).start()
        elif kind == "check":
            if self.runner:
                self.send({"type": "checking"})
                threading.Thread(target=self.runner.run_provider_check, daemon=True).start()
        elif kind == "run":
            if self.runner is None:
                self.send({"type": "error", "message": "Task runner is not active"})
                return
            try:
                self.runner.start(message.get("goal", ""), message.get("url", ""), message.get("tabId"))
            except (ValueError, RuntimeError) as error:
                self.send({"type": "error", "message": str(error)})
        elif kind == "stop":
            if self.runner:
                self.runner.stop_task()
        elif kind == "state":
            self.send({"type": "state", "state": self.runner.current_state() if self.runner else None})
        else:
            self.send({"type": "error", "message": f"Unknown message type: {kind}"})

    def send(self, message):
        with self._send_lock:
            client = self._client
            if client is None:
                raise BridgeError("Firefox extension is not connected")
            _send_frame(client, json.dumps(message).encode("utf-8"))

    def broadcast(self, message):
        try:
            self.send(message)
        except (BridgeError, OSError):
            pass  # broadcasts are best-effort; the sidebar refreshes on reconnect

    def command(self, kind, **payload):
        with self._send_lock:
            client = self._client
            if client is None:
                raise BridgeError(
                    "Firefox extension is not connected. Start the host (jev-firefox), "
                    "install the extension via about:debugging, and open the sidebar."
                )
            command_id = self._next_id
            self._next_id += 1
            entry = {"event": threading.Event()}
            self._pending[command_id] = entry
            _send_frame(client, json.dumps({"id": command_id, "type": kind, **payload}).encode("utf-8"))
        if not entry["event"].wait(COMMAND_TIMEOUT):
            self._pending.pop(command_id, None)
            raise BridgeError(f"Firefox extension did not answer '{kind}' within {COMMAND_TIMEOUT:.0f}s")
        if "error" in entry:
            raise BridgeError(str(entry["error"]))
        return entry.get("result")


class FirefoxBrowser:
    """Drives one live Firefox tab through the extension bridge; the same contract as Browser."""

    def __init__(self, url, tab_id=None, bridge=None):
        self.bridge = bridge if bridge is not None else server()
        self.tab_id = tab_id
        if tab_id is None:
            self.tab_id = self.bridge.command("open", url=url)["tabId"]

    def observe(self, screenshot=True):
        state = None
        for attempt in range(10):
            try:
                state = self.bridge.command("observe", tabId=self.tab_id, screenshot=screenshot)
                break
            except BridgeError as error:
                transient = "navigating" in str(error) or "receiving end" in str(error).lower()
                if attempt == 9 or not transient:
                    raise
                time.sleep(0.05 + 0.05 * attempt)
        state["fingerprint"] = fingerprint(state)
        return state

    def fresh(self, page, action=None):
        if action is not None and action["kind"] in {"click", "select"}:
            node = action["node"]
            if type(node) is not int:
                return False
            current = self.bridge.command("fresh", tabId=self.tab_id, node=node)
            return current == [page["page_key"], page["guards"].get(str(node))]
        current = self.bridge.command("fresh", tabId=self.tab_id, marker=page["marker"])
        return current == page["marker"]

    def act(self, action, page, text=None):
        try:
            if not self.fresh(page, action):
                raise StalePage("Page changed since this decision. Observe again.")
            if action["kind"] == "wait":
                time.sleep(0.1)
                return {"executed": action["id"]}
            result = self.bridge.command("act", tabId=self.tab_id, action=action, text=text)
        except BridgeError as error:
            # A vanished content-script context means the tab navigated mid-action:
            # treat it as a stale page so the agent re-observes instead of dying.
            if "receiving end" in str(error).lower() or "context" in str(error).lower():
                raise StalePage("The tab changed while acting. Observe again.") from None
            raise
        if result.get("stale"):
            raise StalePage("Target changed or is covered. Observe again.")
        if result.get("error"):
            raise RuntimeError(result["error"])
        return result

    def close(self):
        pass  # the tab belongs to the user's browser; the bridge leaves it open


_SERVER = None


def server():
    if _SERVER is None or not _SERVER.connected:
        raise BridgeError(
            "Firefox extension is not connected. Run `uv run --env-file .env jev-firefox`, "
            "load extension/ via about:debugging, and open the sidebar."
        )
    return _SERVER


class TaskRunner:
    """Runs one Agent task at a time on the extension's tab and broadcasts each state."""

    def __init__(self, bridge):
        self.bridge = bridge
        self.agent = None
        self.stopped = False
        self.last_error = None
        self.provider_check = None
        self._lock = threading.Lock()

    def current_state(self):
        if self.agent is None:
            state = {"status": "idle", "history": [], "plan": [], "page": None}
        else:
            state = self.agent.snapshot()
        planner = self.agent.state.get("planner") if self.agent else None
        return {
            **state,
            "policy": policy_description(),
            "planner": planner,
            "error": self.last_error,
            "providers": self.provider_check,
        }

    def run_provider_check(self):
        """Self-test in the background; the result is carried in every state broadcast."""
        if not self._lock.acquire(blocking=False):
            return  # a task is running; providers are clearly working
        try:
            self.provider_check = check_providers()
        finally:
            self._lock.release()
        self._broadcast()

    def start(self, goal, url, tab_id):
        goal = (goal or "").strip()
        if not goal or len(goal) > 2000:
            raise ValueError("Enter 1–2,000 characters")
        if not self._lock.acquire(blocking=False):
            raise ValueError("A task is already running; stop it first")
        self.stopped = False
        self.last_error = None
        threading.Thread(target=self._run, args=(goal, url, tab_id), daemon=True).start()

    def stop_task(self):
        self.stopped = True

    def _run(self, goal, url, tab_id):
        from .agent import Agent  # imported here to keep the module import-light

        try:
            browser = FirefoxBrowser(url, tab_id=tab_id, bridge=self.bridge)
            self.agent = Agent(url, goal, screenshots=True, browser=browser)
            self._broadcast()
            for _state in self.agent.run():
                self._broadcast()
                if self.stopped:
                    break
        except (ValueError, RuntimeError, BridgeError, StalePage) as error:
            # Keep the failure in the state so the sidebar shows it until the next run.
            self.last_error = str(error)
            self.bridge.broadcast({"type": "error", "message": str(error)})
        finally:
            self.agent = None
            self._broadcast()
            self._lock.release()

    def _broadcast(self):
        self.bridge.broadcast({"type": "state", "state": self.current_state()})


def load_environment():
    path = os.path.join(os.getcwd(), ".env")
    if os.path.exists(path):
        with open(path) as handle:
            for line in handle:
                if "=" in line and not line.startswith("#"):
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())


def main():
    global _SERVER
    load_environment()
    port = int(os.environ.get("FIREFOX_BRIDGE_PORT", str(DEFAULT_PORT)))
    token = os.environ.get("FIREFOX_BRIDGE_TOKEN") or None
    _SERVER = BridgeServer(port=port, token=token)
    _SERVER.runner = TaskRunner(_SERVER)
    _SERVER.start()
    print(f"Jev Ultrafast Firefox bridge: ws://127.0.0.1:{_SERVER.port}", flush=True)
    print("Load extension/ in Firefox via about:debugging → This Firefox → Load Temporary Add-on.", flush=True)
    print(f"Policy model: {policy_description()}", flush=True)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
