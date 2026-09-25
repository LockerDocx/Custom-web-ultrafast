"""Text I/O must say its encoding: Windows defaults to a legacy code page.

Two things break without an explicit encoding, and both were real:

  * importing the agent reads `snapshot.js`, which has non-ASCII characters —
    under cp1252 a byte can be undefined and the import dies, so the agent never
    starts;
  * `.env`, the model config and the routing report carry Spanish and emoji, and
    writing them under cp1252 raises UnicodeEncodeError.

The behavioural test runs a subprocess under an ASCII locale, which is exactly
the failure mode a Windows user would hit; CI runs the whole suite that way too.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent

# Directories that are not ours to police (dependencies, caches, build output).
EXCLUDED = {".venv", ".git", "node_modules", "__pycache__", "build", "dist", ".ruff_cache"}

# Text-mode file I/O: two-argument read_text/write_text and open all need a declared encoding
CALLS = re.compile(r"(?:\bopen\(|\.read_text\(|\.write_text\()")


def arguments_of(text, start):
    """The parenthesised argument list that starts at `start`, paren-balanced."""
    depth = 0
    for index in range(start, len(text)):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return text[start:]


def is_text_call(source, match):
    """`Image.open(p)` borrows a method name, so only a bare two-argument call counts."""
    before = source[match.start() - 1] if match.start() else ""
    if match.group(0) == "open(" and (before == "." or before.isalnum() or before == "_"):
        return False
    line_start = source.rfind("\n", 0, match.start()) + 1
    return "re.compile(" not in source[line_start : match.end()]


def test_every_text_file_operation_declares_its_encoding():
    offenders = []
    for path in sorted(ROOT.rglob("*.py")):
        if EXCLUDED & set(path.parts):
            continue
        source = path.read_text(encoding="utf-8")
        for match in CALLS.finditer(source):
            if not is_text_call(source, match):
                continue
            call = arguments_of(source, match.end() - 1)
            if '"wb"' in call or '"rb"' in call or "'wb'" in call or "'rb'" in call:
                continue  # binary mode carries no text
            if "encoding=" in call:
                continue
            line = source[: match.start()].count("\n") + 1
            offenders.append(f"{path.relative_to(ROOT)}:{line}: {call[:60]}")
    assert not offenders, "text I/O without an explicit encoding:\n  " + "\n  ".join(offenders)


def test_the_extension_sources_and_the_static_pages_are_read_as_utf8():
    for name in ("browser.py", "demo.py"):
        source = (ROOT / "jev_ultrafast" / name).read_text(encoding="utf-8")
        assert 'read_text(encoding="utf-8")' in source, f"{name} must decode those files as UTF-8"


@pytest.mark.skipif(os.name != "posix", reason="the ASCII locale is set through the environment")
def test_the_agent_starts_and_stores_accented_text_under_a_legacy_locale(tmp_path):
    """LC_ALL=C gives Python a strict single-byte locale, like Windows' cp1252."""
    script = tmp_path / "check.py"
    script.write_text(
        """
import json, os, sys
sys.path.insert(0, r"{root}")

# 1. importing the agent reads snapshot.js (non-ASCII): the Windows killer
import jev_ultrafast.browser as browser
print("snapshot:", len(browser.READ_STATE))

# 2. the sidebar's static pages, also non-ASCII
import jev_ultrafast.demo  # noqa: F401

# 3. a key pasted next to an accented comment, as a user would write it
from jev_ultrafast import providers
env = os.path.join(os.getcwd(), ".env")
with open(env, "w", encoding="utf-8") as handle:
    handle.write("# Configuración\\nGROQ_API_KEY=\\n")
providers.save_key("GROQ_API_KEY", "gsk_acentuado")
print("env:", open(env, encoding="utf-8").read().strip().splitlines()[-1])

# 4. a config the panel writes, with the accents a Spanish user has on screen
from jev_ultrafast import parameters
print("config:", json.dumps(parameters.current_selection(), ensure_ascii=False)[:40])
""".format(root=ROOT),
        encoding="utf-8",
    )
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "LC_ALL": "C",
        "LANG": "C",
        "PYTHONUTF8": "0",  # refuse the UTF-8 mode: this must work without it
        "PYTHONCOERCECLOCALE": "0",
        "PYTHONIOENCODING": "",
    }
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    assert "UnicodeDecodeError" not in result.stderr
    assert "snapshot:" in result.stdout and "GROQ_API_KEY=gsk_acentuado" in result.stdout


def test_a_bom_written_by_notepad_does_not_hide_the_first_key(tmp_path):
    """.env files saved by Notepad start with a BOM; the key must still be found.

    Two shapes matter: the normal Notepad BOM, and a doubled one (a tool that
    appends to a BOM'd file leaves the second BOM inside the first line).
    """
    from jev_ultrafast import providers

    for label, raw in (("single BOM", "\ufeff"), ("doubled BOM", "\ufeff\ufeff")):
        env = tmp_path / f"{label.replace(' ', '-')}.env"
        env.write_bytes(raw.encode("utf-8") + b"GROQ_API_KEY=\n")
        providers.save_key("GROQ_API_KEY", "gsk_bom", path=env)
        saved = env.read_text(encoding="utf-8-sig").splitlines()
        assert saved.count("GROQ_API_KEY=gsk_bom") == 1, (label, saved)
        assert not any("\ufeff" in line for line in saved), (label, saved)
