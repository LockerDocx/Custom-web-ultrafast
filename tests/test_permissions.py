"""Contracts for the permission center (MVP-5): scope levels, enforcement, audit.

No browser, no paid APIs; every decision path is exercised offline.
"""

import json

import pytest

from jev_ultrafast import permissions
from jev_ultrafast.tools import ToolBox, ToolError, classify_command


@pytest.fixture(autouse=True)
def isolated_permissions(tmp_path, monkeypatch):
    monkeypatch.setattr(permissions, "PERMISSIONS_PATH", tmp_path / "permissions.json")
    yield


def read_audit(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


# ── levels, persistence, defaults ────────────────────────────────────────────


def test_every_scope_has_a_default_level():
    levels = permissions.defaults()
    assert set(levels) == {"browser", "terminal", "filesystem", "network", "clipboard", "downloads"}
    assert set(permissions.LEVELS) == {"allow", "ask", "deny"}
    assert permissions.level("browser") == "allow"
    assert permissions.level("clipboard") == "ask"  # reading the clipboard starts cautious


def test_set_level_validates_persists_and_resets():
    permissions.set_level("network", "deny")
    assert permissions.level("network") == "deny"
    assert json.loads(permissions.PERMISSIONS_PATH.read_text(encoding="utf-8"))["levels"]["network"] == "deny"
    with pytest.raises(ValueError):
        permissions.set_level("network", "sometimes")
    with pytest.raises(ValueError):
        permissions.set_level("telepathy", "allow")
    permissions.reset()
    assert permissions.level("network") == "allow"


def test_describe_is_what_the_sidebar_renders():
    described = permissions.describe()
    assert set(described["levels"]) == {"browser", "terminal", "filesystem", "network", "clipboard", "downloads"}
    keys = [scope["key"] for scope in described["scopes"]]
    assert keys[0] == "browser" and "clipboard" in keys
    for scope in described["scopes"]:
        assert scope["label"] and scope["hint"]


# ── terminal: the scope narrows the command policy, never widens it ──────────


def test_scope_deny_blocks_even_read_only_commands():
    assert permissions.terminal_verdict("ls", classify_command, "deny") == "scope-denied"


def test_scope_ask_upgrades_allows_to_approvals():
    assert permissions.terminal_verdict("ls", classify_command, "ask") == "approve"
    assert permissions.terminal_verdict("cat notes.md", classify_command, "ask") == "approve"


def test_no_scope_level_lifts_the_destructive_rule():
    for level in permissions.LEVELS:
        assert permissions.terminal_verdict("rm -rf /", classify_command, level) == "deny"
        assert permissions.terminal_verdict("sudo something", classify_command, level) == "deny"


def test_scope_allow_keeps_the_plain_policy():
    assert permissions.terminal_verdict("ls -la", classify_command, "allow") == "allow"
    assert permissions.terminal_verdict("curl http://x", classify_command, "allow") == "deny"
    assert permissions.terminal_verdict("python build.py", classify_command, "allow") == "approve"


# ── PermissionCenter.check ───────────────────────────────────────────────────


def test_check_allow_runs_without_asking():
    asked = []
    center = permissions.PermissionCenter(request_approval=lambda detail: asked.append(detail) or True)
    decision = center.check("web_search", "flights")
    assert decision["allowed"] is True
    assert decision["scope"] == "network" and decision["level"] == "allow"
    assert asked == []  # the allow level never bothers the user


def test_check_ask_requires_an_explicit_approval():
    center = permissions.PermissionCenter(request_approval=lambda detail: False)
    decision = center.check("clipboard_write", "draft")
    assert decision["allowed"] is False
    assert decision["decision"] == "not-approved" and "did not approve" in decision["reason"]


def test_check_ask_approved_runs():
    seen = []
    center = permissions.PermissionCenter(request_approval=lambda detail: seen.append(detail) or True)
    decision = center.check("clipboard_write", "draft")
    assert decision["allowed"] is True and decision["decision"] == "approved"
    assert seen and seen[0].startswith("[clipboard]")


def test_check_deny_refuses_with_an_actionable_message():
    permissions.set_level("downloads", "deny")
    center = permissions.PermissionCenter()
    decision = center.check("download_file", "report.pdf")
    assert decision["allowed"] is False
    assert decision["decision"] == "denied" and "permission center" in decision["reason"]


def test_ungated_tools_are_not_scoped():
    decision = permissions.PermissionCenter().check("list_files", ".")
    assert decision == {"allowed": True, "scope": None, "level": None, "decision": "ungated", "reason": ""}


# ── enforcement inside the ToolBox + audit ───────────────────────────────────


def make_box(tmp_path, **kwargs):
    audit = tmp_path / "audit.jsonl"
    return ToolBox(tmp_path / "ws", audit_path=audit, **kwargs), audit


def test_denied_scope_stops_the_tool_and_lands_in_the_audit(tmp_path):
    center = permissions.PermissionCenter()
    permissions.set_level("filesystem", "deny")
    box, audit = make_box(tmp_path, permission_center=center)
    with pytest.raises(ToolError) as raised:
        box.call("write_file", {"path": "a.txt", "content": "hi"})
    assert "filesystem scope is set to deny" in str(raised.value)
    entry = read_audit(audit)[-1]
    assert entry["tool"] == "write_file" and entry["decision"] == "denied"
    assert entry["scope"] == "filesystem" and entry["level"] == "deny"


def test_ask_level_audits_approvals_and_refusals(tmp_path):
    decisions = []
    center = permissions.PermissionCenter(request_approval=lambda detail: decisions.append(detail) or True)
    permissions.set_level("downloads", "ask")
    box, audit = make_box(tmp_path, permission_center=center)
    entry = read_audit(audit) if audit.exists() else []
    box._gate("download_file", "x.pdf")
    assert not entry
    assert read_audit(audit)[-1]["decision"] == "approved"


def test_allowed_tools_carry_their_scope_into_the_audit(tmp_path):
    center = permissions.PermissionCenter()
    box, audit = make_box(tmp_path, permission_center=center)
    box._gate("browser_task", "open example.com")
    box._audit("browser_task", {"goal": "x"}, **box._decision_fields(), ok=True)
    entry = read_audit(audit)[-1]
    assert entry["scope"] == "browser" and entry["level"] == "allow" and entry["decision"] == "allowed"


def test_terminal_scope_deny_blocks_run_command_without_an_approval_prompt(tmp_path):
    asked = []
    center = permissions.PermissionCenter(request_approval=lambda detail: asked.append(detail) or True)
    permissions.set_level("terminal", "deny")
    box, audit = make_box(tmp_path, request_approval=lambda c: True, permission_center=center)
    with pytest.raises(ToolError) as raised:
        box.call("run_command", {"command": "ls"})
    assert "terminal scope is set to deny" in str(raised.value)
    assert asked == []  # nothing to approve: the scope forbids it outright
    assert read_audit(audit)[-1]["verdict"] == "scope-denied"


def test_terminal_scope_ask_routes_every_command_through_approval(tmp_path):
    approvals = []
    box, audit = make_box(
        tmp_path,
        request_approval=lambda command: approvals.append(command) is None,
        permission_center=permissions.PermissionCenter(),
    )
    permissions.set_level("terminal", "ask")
    box.call("run_command", {"command": "ls"})  # approved: it runs
    assert approvals == ["ls"]  # even a read-only command asked first
    assert read_audit(audit)[-1]["verdict"] == "approve"
    approvals.clear()
    denied, denied_audit = make_box(
        tmp_path / "denied",
        request_approval=lambda command: False,
        permission_center=permissions.PermissionCenter(),
    )
    with pytest.raises(ToolError):
        denied.call("run_command", {"command": "ls"})
    assert read_audit(denied_audit)[-1]["approved"] is False


def test_destructive_commands_stay_denied_under_every_scope_level(tmp_path):
    for level in permissions.LEVELS:
        permissions.set_level("terminal", level)
        box, _audit = make_box(tmp_path, request_approval=lambda command: True)
        with pytest.raises(ToolError):
            box.call("run_command", {"command": "rm -rf /"})


# ── clipboard tools (the scope needs an enforcement point) ───────────────────


def test_clipboard_tools_exist_and_are_gated_by_their_scope(tmp_path, monkeypatch):
    assert "clipboard_read" in ToolBox(tmp_path / "ws").registry
    box, _audit = make_box(tmp_path, permission_center=permissions.PermissionCenter())
    # default level is "ask"; without an approval the tool refuses
    with pytest.raises(ToolError) as raised:
        box.call("clipboard_read", {})
    assert "did not approve" in str(raised.value)


def test_clipboard_argv_is_platform_shaped(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    from jev_ultrafast import tools

    monkeypatch.setattr(tools.sys, "platform", "linux")
    assert tools._clipboard_argv("read") == ["xclip", "-selection", "clipboard", "-o"]
    assert tools._clipboard_argv("write") == ["xclip", "-selection", "clipboard", "-i"]
    monkeypatch.setattr(tools.sys, "platform", "darwin")
    assert tools._clipboard_argv("read") == ["pbpaste"]


def test_missing_clipboard_binary_says_so(monkeypatch):
    from jev_ultrafast import tools

    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr(tools.sys, "platform", "linux")
    with pytest.raises(ToolError) as raised:
        tools._clipboard_argv("read")
    assert "not installed" in str(raised.value)
