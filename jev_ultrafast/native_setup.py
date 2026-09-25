"""Register the native-messaging host, so Firefox starts Jev by itself.

Firefox deliberately never lets an add-on install or launch local software on its
own: the user (or the installer they ran) has to point the browser at the program
once. This module is that one step. After it, the sidebar opening the port *is*
starting the agent: no double-click, no window, no port, and the host dies when
Firefox does.

The registration is per user and needs no administrator rights:
  * Linux/macOS: a small JSON manifest in the browser's own folder.
  * Windows:     the same JSON plus one registry value under HKEY_CURRENT_USER.
"""

import json
import os
import sys
from pathlib import Path
from shutil import which

HOST_NAME = "jev_ultrafast_host"
EXTENSION_ID = "jev-ultrafast@custom-web-ultrafast"  # must match extension/manifest.json
BUILD_SCRIPT = "jev-firefox-native"
MANIFEST_NAME = f"{HOST_NAME}.json"


def executable(root=None):
    """The entry point Firefox should launch (an executable, never a shell).

    The starter builds one inside the checkout; an install without a local venv
    (`pip install -e .`, a shared environment) has one on PATH instead. Prefer the
    checkout's own, because that is the one tied to this folder's code and .env.
    """
    root = Path(root or repo_root())
    scripts = ("Scripts", ".exe") if os.name == "nt" else ("bin", "")
    local = root / ".venv" / scripts[0] / f"{BUILD_SCRIPT}{scripts[1]}"
    if local.exists():
        return local
    return Path(which(BUILD_SCRIPT) or local)


def manifest_path():
    """Where this browser looks for the host manifest of this user."""
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "Mozilla" / "NativeMessagingHosts" / MANIFEST_NAME
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Mozilla" / "NativeMessagingHosts" / MANIFEST_NAME
    return Path.home() / ".mozilla" / "native-messaging-hosts" / MANIFEST_NAME


def manifest_for(root=None, path=None):
    return {
        "name": HOST_NAME,
        "description": "Jev Ultrafast local host: plans and executes browser missions for the sidebar.",
        "path": str(path or executable(root)),
        "type": "stdio",
        "allowed_extensions": [EXTENSION_ID],  # only our add-on may talk to it
    }


def registry_key():
    return rf"SOFTWARE\Mozilla\NativeMessagingHosts\{HOST_NAME}"


def _write_registry(value):
    import winreg  # Windows only

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, registry_key()) as key:
        winreg.SetValueEx(key, None, 0, winreg.REG_SZ, str(value))


def _delete_registry():
    import winreg

    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, registry_key())
    except FileNotFoundError:
        pass


def repo_root():
    """The checkout this module lives in (not the cwd: the browser picks the cwd)."""
    root = Path(__file__).resolve().parents[1]
    return root if (root / "pyproject.toml").exists() else Path.cwd()


def register(root=None, path=None):
    """Write the manifest (and the registry value on Windows). Idempotent."""
    root = Path(root or repo_root())
    target = executable(root) if path is None else Path(path)
    destination = manifest_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(manifest_for(root, target), indent=2) + "\n")
    if os.name == "nt":
        _write_registry(destination)
    return {"manifest": destination, "executable": target, "exists": target.exists()}


def unregister():
    """Undo register(): the browser stops launching Jev by itself."""
    destination = manifest_path()
    removed = False
    try:
        destination.unlink()
        removed = True
    except FileNotFoundError:
        pass
    if os.name == "nt":
        _delete_registry()
    return removed


def status():
    """What the sidebar and the starters report, without changing anything."""
    destination = manifest_path()
    entry = {"manifest": destination, "registered": False, "executable": None, "exists": False}
    try:
        data = json.loads(destination.read_text())
    except (OSError, ValueError):
        return entry
    entry["registered"] = data.get("name") == HOST_NAME and EXTENSION_ID in (data.get("allowed_extensions") or [])
    entry["executable"] = data.get("path")
    entry["exists"] = bool(entry["executable"]) and Path(entry["executable"]).exists()
    return entry


def main(argv=None):
    """`jev-register-host` / `python -m jev_ultrafast.native_setup`."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    if "--unregister" in arguments:
        gone = unregister()
        print("Jev will no longer be started by Firefox." if gone else "Nothing was registered.")
        return 0
    if "--status" in arguments:
        state = status()
        print(f"registered: {state['registered']}  host: {state['executable'] or '-'}  present: {state['exists']}")
        return 0 if state["registered"] and state["exists"] else 1
    entry = register()
    print(f"Firefox will now start Jev by itself ({entry['manifest']}).")
    if not entry["exists"]:
        print("Note: the host program is not built yet - run the starter once, then re-run this.", file=sys.stderr)
        return 1
    print("You no longer need to double-click the starter: open the sidebar and it runs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
