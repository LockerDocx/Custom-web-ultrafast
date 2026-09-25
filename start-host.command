#!/bin/bash
# Double-clickable starter for the Jev Agent Firefox bridge host (macOS).
# If macOS blocks the file the first time: right-click → Open → Open.

cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1 || ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >/dev/null 2>&1; then
  echo ""
  echo " [!] Python 3.12 or newer is required."
  echo "     Install it from https://www.python.org/downloads/ and run this file again."
  read -n 1 -s -r -p "Press any key to close..."
  echo ""
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
    read -n 1 -s -r -p "Press any key to close..."
    echo ""
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
echo "Host starting. KEEP THIS WINDOW OPEN while you use the sidebar."
echo ""
echo "First time? It will ask for one free API key - paste it and press Enter."
echo "Get one in 2 minutes at https://console.groq.com/keys"
echo ""
echo "Now in Firefox:"
echo "  1. Type about:debugging in the address bar and press Enter"
echo "  2. Click 'This Firefox' then 'Load Temporary Add-on...'"
echo "  3. Open this folder, then the 'extension' folder, pick 'manifest.json'"
echo "  4. Open the Jev sidebar with the toolbar button"
echo ""
exec .venv/bin/jev-firefox
