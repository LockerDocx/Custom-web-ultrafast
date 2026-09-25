"""What the sidebar shows while a mission runs.

The panel is the only surface the user has, and until now nothing tested it: the
other sidebar tests in this suite only check that element ids exist and that the
message names line up. These tests run `sidebar.js` for real (in Node, against a
stub DOM, see tests/sidebar_harness.mjs), feed it the same messages the host
broadcasts, and assert on what a user would actually see:

- a progress bar that is only a percentage when something real was measured,
- a conversation view (you → steps → answer) and a timestamped log,
- a verdict that says whether the agent can run at all.

They skip when Node is not installed, so the Python-only environments stay green.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HARNESS = ROOT / "tests" / "sidebar_harness.mjs"


@pytest.fixture(scope="module")
def panel():
    """Run the sidebar harness once; every test below reads its report."""
    node = shutil.which("node")
    if node is None or not HARNESS.exists():
        pytest.skip("node is not available (the panel is not rendered in this environment)")
    result = subprocess.run(
        [node, str(HARNESS), str(ROOT / "extension" / "sidebar" / "sidebar.js")],
        capture_output=True,
        timeout=180,
        cwd=ROOT,
    )
    # Decode explicitly: this suite also runs under a legacy code page (CI asserts it),
    # where the locale encoding is not UTF-8 and would break on an emoji.
    stderr = result.stderr.decode("utf-8", errors="replace")[-2000:]
    assert result.returncode == 0, f"the sidebar crashed:\n{stderr}"
    return json.loads(result.stdout.decode("utf-8", errors="replace"))


def text(html):
    """The visible text of a rendered fragment, tags stripped and spaces collapsed."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def test_the_conversation_reads_like_a_conversation(panel):
    """You asked → the agent worked → the answer, in that order."""
    conversation = text(panel["chatDone"])
    asked = conversation.index("Book the cheapest direct flight")
    worked = conversation.index("web_search")
    answered = conversation.index("final answer")
    closed = conversation.index("Finished")
    assert asked < worked < answered, "the conversation is not in the order it happened"
    assert answered < closed, "the closing line must come after the answer it closes"
    assert "The cheapest direct flight is 84 EUR at 07:15." in conversation
    assert "12 results" in conversation, "a tool call must show what it returned"


def test_the_steps_arrive_while_it_works_not_only_at_the_end(panel):
    """Halfway through, the user already sees the first step and the live text."""
    mid = text(panel["chatMidRun"])
    assert "I will search for flights first" in mid
    assert "web_search" in mid
    assert "1 step · up to 25 · 7.3 s · 3.1k tokens" in panel["metaMidRun"]


def test_the_progress_bar_never_invents_a_percentage(panel):
    """While running with no plan there is no total, so the bar is indeterminate."""
    assert panel["barMidRun"]["indeterminate"] is True
    assert panel["barMidRun"]["width"] == "", "a width would be a made-up percentage"
    assert "at most 25" in text(panel["noteMidRun"])
    # With a real plan, the bar is determinate and says where it is.
    assert panel["barPlan"] == {"width": "33%", "label": "step 2 of 3", "indeterminate": False}
    # And it fills when the run is over.
    assert panel["barDone"]["width"] == "100%"
    assert panel["barDone"]["label"] == "done ✓"
    assert panel["barDone"]["done"] is True


def test_the_tools_and_errors_leave_a_trace(panel):
    """Nothing that happened is silent: the log keeps level, time and message."""
    log = panel["logView"]["html"]
    assert re.search(r"\d\d:\d\d:\d\d</span><span class=\"lvl\">SYSTEM", log)
    assert "Step 2/3 · Search flights" in log, "a plan step must be logged when it starts"
    assert 'class="error"' in log and "Groq rejected the key (401)" in log
    assert "Groq rejected the key (401)" in text(panel["chatError"])
    assert panel["logView"]["chatHidden"] is True and panel["logView"]["logHidden"] is False
    assert panel["chatView"] == {"chatHidden": False, "logHidden": True}


def test_the_verdict_is_one_glance(panel):
    """Green with the models that will run, red naming the roles that cannot."""
    ready = panel["readyOk"]
    assert ready["dot"] == "🟢" and ready["bad"] is False
    assert "Ready to run" in ready["text"]
    assert "Planner" in ready["text"] and "Executor" in ready["text"] and "Text writer" in ready["text"]
    assert "z-ai/glm-5.3" in ready["text"], "the verdict names the model that will run"
    not_ready = panel["readyBad"]
    assert not_ready["dot"] == "🔴" and not_ready["bad"] is True
    assert "Not ready" in not_ready["text"]
    assert "Executor" in not_ready["text"] and "Text writer" in not_ready["text"]
    assert "one free key" in not_ready["text"].lower()


def test_the_verdict_says_where_the_keys_are_read_from(panel):
    """"Nothing configured" must come with the file the agent looked in: a key in another
    file was the whole reason a saved NVIDIA key looked missing."""
    assert "Not ready" in panel["readyBad"]["text"]
    assert "~/.config/jev-ultrafast/.env" in panel["readyBad"]["text"]


def test_a_model_that_did_not_answer_is_not_reported_as_a_missing_model(panel):
    """A role with a model that stayed silent is not a missing key.

    Reported 2026-09-25: the panel showed `Planner · nvidia:z-ai/glm-5.3` in red and then said the
    Planner and the Executor "have no model" - the model was right there on the line above. That
    wording sends the user hunting for a key they have already pasted; what happened is that the
    endpoint did not answer, and that is what the panel has to say.
    """
    unreachable = text(panel["readyUnreachable"]["text"])
    assert "did not answer" in unreachable
    assert "have no model" not in unreachable, "a configured model must not be called missing"
    assert "slow or unreachable" in unreachable
    assert "Test setup to try again" in unreachable, "the fix is a retry, and the panel says so"
    assert "Executor" in unreachable
    # and the "no model" wording is still reserved for the case it describes
    assert "have no model" in text(panel["readyBad"]["text"])


def test_a_self_test_shows_the_wait_instead_of_the_old_verdict(panel):
    """Free endpoints take their time; the panel must say it is working, with real seconds.

    The clock is the only number here: 12 s and then 13 s, both measured.
    """
    checking = text(panel["readyChecking"]["text"])
    assert "Testing every model connection" in checking
    assert panel["readyChecking"]["dot"] == "\u23f3"
    assert panel["readyChecking"]["testing"] is True
    assert panel["readyChecking"]["buttonDisabled"] is True, "a second press is dropped anyway"
    assert panel["readyTick"]["text"] != panel["readyChecking"]["text"], "the counter must tick"
    first = int(re.search(r"(\d+) s", checking).group(1))
    second = int(re.search(r"(\d+) s", text(panel["readyTick"]["text"])).group(1))
    assert second > first, f"elapsed time went backwards: {first} then {second}"
    assert text(panel["readyTick"]["text"]).replace(f"{second} s", "N s") == checking.replace(
        f"{first} s", "N s"
    ), "only the number may change between ticks"


def test_the_panel_returns_to_a_verdict_when_the_check_answers(panel):
    """After a check the button works again and a verdict is back."""
    after = panel["readyAfterCheck"]
    assert after["checking"] is False and after["buttonDisabled"] is False
    assert "Ready to run" in text(after["text"])


def test_clearing_the_view_does_not_stop_the_run(panel):
    """Clear empties the panel; the run continues in the background."""
    assert panel["afterClear"]["hidden"] is True


# ── the contracts the panel depends on ───────────────────────────────────────


def test_the_roles_are_named_the_same_in_the_host_and_the_panel():
    """A role must never appear under two names (the panel said "Executor" while
    the message said "policy role", which read like two different problems)."""
    from jev_ultrafast import providers

    script = (ROOT / "extension" / "sidebar" / "sidebar.js").read_text(encoding="utf-8")
    block = re.search(r"const ROLE_NAMES = \{(.*?)\};", script).group(1)
    panel_labels = dict(re.findall(r'(\w+):\s*"([^"]+)"', block))
    assert panel_labels == providers.ROLE_LABELS


def test_the_host_tells_the_panel_how_many_steps_a_run_may_take():
    """The bar says "up to N" instead of guessing: N has to come from the host."""
    from jev_ultrafast.orchestrator import MAX_ORCHESTRATOR_STEPS

    state = (ROOT / "jev_ultrafast" / "firefox.py").read_text(encoding="utf-8")
    assert '"step_budget": MAX_ORCHESTRATOR_STEPS' in state
    assert MAX_ORCHESTRATOR_STEPS > 0


@pytest.fixture
def clean_env(monkeypatch):
    """A fresh install: no key, no explicit provider for any role."""
    for name in (
        "GROQ_API_KEY", "NVIDIA_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY", "TYPESAFE_API_KEY",
        "POLICY_API_KEY", "PLANNER_API_KEY", "TEXT_MODEL_API_KEY",
        "POLICY_PROVIDER", "PLANNER_PROVIDER", "TEXT_MODEL_PROVIDER",
        "POLICY_BASE_URL", "PLANNER_BASE_URL", "TEXT_MODEL_BASE_URL",
        "POLICY_MODEL", "PLANNER_MODEL", "TEXT_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    yield monkeypatch


def test_a_role_without_a_model_says_so_in_the_panels_words(clean_env):
    """The message names the role the way the panel shows it, and how to fix it."""
    from jev_ultrafast import providers

    clean_env.delenv("GROQ_API_KEY", raising=False)
    clean_env.setenv("POLICY_PROVIDER", "groq")
    with pytest.raises(ValueError) as error:
        providers.resolve("policy")
    message = str(error.value)
    assert "POLICY_API_KEY" in message, "the user needs to know which variable is missing"
    assert providers.ROLE_LABELS["policy"] in message, "the role must be named as the panel names it"
    assert "console.groq.com" in message, "and where the free key comes from"
