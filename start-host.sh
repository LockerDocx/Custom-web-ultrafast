#!/bin/bash
# Starter for the Jev Agent Firefox bridge host (Linux).
# Run it from a file manager or a terminal.

cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1 || ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >/dev/null 2>&1; then
  echo ""
  echo " [!] Python 3.12 or newer is required."
  echo "     Install it - e.g. sudo apt install python3.12 python3.12-venv - and run this file again."
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo ""
  echo "First run: preparing the agent. About one minute, internet needed..."
  python3 -m venv .venv || exit 1
  .venv/bin/python -m pip install --quiet --upgrade pip
  if ! .venv/bin/python -m pip install --quiet -e ".[documents]"; then
    echo ""
    echo " [!] Installation failed. Check your internet connection and run this file again."
    exit 1
  fi
fi

# Earlier templates shipped a wrong NVIDIA model id (zai/ instead of z-ai/): fix it in place.
if [ -f ".env" ] && grep -q "zai/glm-5.3" .env; then
  sed -i.bak 's|zai/glm-5\.3|z-ai/glm-5.3|g' .env
  echo "Fixed an outdated model id in .env (zai/ → z-ai/). Backup saved as .env.bak"
fi

if [ ! -f ".env" ]; then
  cp .env.example .env
fi

echo ""
echo "Registering the host with Firefox..."
if .venv/bin/jev-register-host >/dev/null 2>&1; then
  echo "  Done: from now on the sidebar starts Jev by itself - you will not need this window again."
  echo "  This one stays open only as a fallback: if the panel says offline, it is to blame."
  echo ""
else
  echo "  [!] Could not register it (Firefox will not start Jev on its own)."
  echo "      Keep this window open while you use the agent - it still works exactly the same."
  echo ""
fi
echo ""
echo "Host starting. KEEP THIS WINDOW OPEN while you use the sidebar."
echo ""
echo "Paste your free API key in the sidebar - it will ask (2 minutes at https://console.groq.com/keys)."
echo ""
echo "Now in Firefox:"
echo "  1. Type about:debugging in the address bar and press Enter"
echo "  2. Click 'This Firefox' then 'Load Temporary Add-on...'"
echo "  3. Open this folder, then the 'extension' folder, pick 'manifest.json'"
echo "  4. Open the Jev sidebar with the toolbar button"
echo ""
exec .venv/bin/jev-firefox
