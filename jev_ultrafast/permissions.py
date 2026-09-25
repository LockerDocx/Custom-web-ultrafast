"""Permission center (MVP-5): per-tool scopes with allow / ask / deny levels.

The command policy in tools.py (read-only allow, destructive deny, everything
else asks) stays as the terminal invariant. On top of it, the user controls six
scopes from the sidebar (spec §11): browser, terminal, filesystem, network,
clipboard and downloads. A scope narrows what its tools may do:

- allow: the tool runs under its own safety policy (audited),
- ask:   every use of the tool needs an explicit sidebar approval,
- deny:  the tool is unavailable for this run.

Two invariants no scope can lift: destructive commands are always denied and
secret reads are always blocked (spec §8.1). Levels persist in
artifacts/permissions.json so a restart keeps the user's decision.
"""

import json
import os
from pathlib import Path

PERMISSIONS_PATH = Path(os.environ.get("JEV_PERMISSIONS", "artifacts/permissions.json"))

LEVELS = ("allow", "ask", "deny")

SCOPES = {
    "browser": {
        "label": "Browser",
        "hint": "Live tab missions and the browser_task tool",
        "default": "allow",
    },
    "terminal": {
        "label": "Terminal",
        "hint": "run_command; destructive commands stay denied whatever this says",
        "default": "allow",
    },
    "filesystem": {
        "label": "Files",
        "hint": "Writing files in the task workspace (reads stay allowed inside it)",
        "default": "allow",
    },
    "network": {
        "label": "Network",
        "hint": "web_search, read_page, download_file hosts (JEV_ALLOWED_HOSTS narrows the list)",
        "default": "allow",
    },
    "clipboard": {
        "label": "Clipboard",
        "hint": "Any tool that reads or writes the system clipboard",
        "default": "ask",
    },
    "downloads": {
        "label": "Downloads",
        "hint": "download_file (25 MB cap, workspace only)",
        "default": "allow",
    },
}

# Which scope gates which tool; tools absent from this map are ungated.
TOOL_SCOPE = {
    "browser_task": "browser",
    "run_command": "terminal",
    "write_file": "filesystem",
    "web_search": "network",
    "read_page": "network",
    "download_file": "downloads",
    "clipboard_read": "clipboard",
    "clipboard_write": "clipboard",
}


def defaults():
    return {scope: meta["default"] for scope, meta in SCOPES.items()}


def load():
    """The persisted levels, missing scopes filled with their default."""
    levels = defaults()
    try:
        stored = json.loads(PERMISSIONS_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return levels
    if not isinstance(stored, dict):
        return levels
    for scope, level in (stored.get("levels") or {}).items():
        if scope in SCOPES and level in LEVELS:
            levels[scope] = level
    return levels


def save(levels):
    try:
        PERMISSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
        PERMISSIONS_PATH.write_text(json.dumps({"levels": levels}, indent=2), encoding="utf-8")
    except OSError:
        pass  # a read-only filesystem must not break a run


def level(scope):
    return load().get(scope, SCOPES.get(scope, {}).get("default", "allow"))


def set_level(scope, value):
    scope = (scope or "").strip()
    value = (value or "").strip().lower()
    if scope not in SCOPES:
        raise ValueError(f"Unknown scope: {scope}")
    if value not in LEVELS:
        raise ValueError(f"Unknown level: {value} (use allow, ask or deny)")
    levels = load()
    levels[scope] = value
    save(levels)
    return levels


def reset():
    levels = defaults()
    save(levels)
    return levels


def describe():
    """What the sidebar renders: every scope with its level and purpose."""
    levels = load()
    return {
        "levels": levels,
        "scopes": [
            {
                "key": scope,
                "label": meta["label"],
                "hint": meta["hint"],
                "level": levels.get(scope, meta["default"]),
                "default": meta["default"],
            }
            for scope, meta in SCOPES.items()
        ],
    }


class PermissionCenter:
    """Runtime enforcement: one scope check per gated tool, with audit hooks.

    `on_decision` is ToolBox._audit, so refusals and approvals land in the same
    audit log as the tool calls themselves (spec §11).
    """

    def __init__(self, request_approval=None, on_decision=None):
        self.request_approval = request_approval or (lambda _detail: False)
        # None means "audit through whoever wires me up": ToolBox installs its
        # own audit hook, the TaskRunner installs the shared audit log.
        self.on_decision = on_decision

    def _record(self, **fields):
        if self.on_decision is not None:
            self.on_decision(**fields)

    def describe(self):
        return describe()

    def level(self, scope):
        return level(scope)

    def set_level(self, scope, value):
        levels = set_level(scope, value)
        self._record(
            tool="permissions", args=json.dumps({"scope": scope, "level": value}),
            ok=True, scope=scope, level=value, decision="set", preview=f"{scope}={value}",
        )
        return levels

    def check(self, tool, detail=""):
        """Decide whether a gated tool may run; asks the user at the 'ask' level."""
        scope = TOOL_SCOPE.get(tool)
        if scope is None:
            return {"allowed": True, "scope": None, "level": None, "decision": "ungated", "reason": ""}
        current = level(scope)
        if current == "deny":
            decision = {
                "allowed": False, "scope": scope, "level": current, "decision": "denied",
                "reason": f"The {scope} scope is set to deny, so '{tool}' is unavailable. "
                          "Change it in the permission center if you want it back.",
            }
        elif current == "ask":
            approved = bool(self.request_approval(f"[{scope}] {tool}: {str(detail)[:160]}"))
            decision = {
                "allowed": approved, "scope": scope, "level": current,
                "decision": "approved" if approved else "not-approved",
                "reason": "" if approved else f"The user did not approve '{tool}' (the {scope} scope is set to ask).",
            }
        else:
            decision = {"allowed": True, "scope": scope, "level": current, "decision": "allowed", "reason": ""}
        if current != "allow":
            # ask/deny outcomes are security-relevant even when the tool then fails
            self._record(
                tool=tool, args=json.dumps({"detail": str(detail)[:200]}), ok=decision["allowed"],
                scope=scope, level=current, decision=decision["decision"], error=decision["reason"] or None,
                preview=decision["reason"] or f"{tool} allowed ({scope}={current})",
            )
        return decision


def terminal_verdict(command, classify, scope_level=None):
    """Combine the command policy with the terminal scope.

    `classify` is tools.classify_command: the safety policy owns deny (never
    lifted). The scope can only narrow: ask upgrades an allow to approve,
    deny blocks everything.
    """
    scope_level = scope_level if scope_level is not None else level("terminal")
    verdict = classify(command)
    if verdict == "deny":
        return "deny"  # the destructive rule is reported as itself, at every scope level
    if scope_level == "deny":
        return "scope-denied"
    if scope_level == "ask":
        return "approve"
    return verdict
