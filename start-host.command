#!/bin/bash
# Double-clickable starter for the Jev Ultrafast Firefox bridge host (macOS).
# Prepares a private Python environment and runs the host. First run also
# creates the .env settings file. If macOS blocks the file: right-click → Open.

cd "$(dirname "$0")" || exit 1

if ! command -v python3 >/dev/null 2>&1 || ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" >/dev/null 2>&1; then
  echo "Python 3.12 or newer is required."
  echo "Install it from https://www.python.org/downloads/ and run this file again."
  read -n 1 -s -r -p "Press any key to close..."
  echo
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Preparing the host for the first run. This can take a minute..."
  python3 -m venv .venv || exit 1
  .venv/bin/python -m pip install --quiet --upgrade pip
  if ! .venv/bin/python -m pip install --quiet -e .; then
    echo "Installation failed. Check your internet connection and run this file again."
    read -n 1 -s -r -p "Press any key to close..."
    echo
    exit 1
  fi
fi

if [ ! -f ".env" ]; then
  cp .env.example .env
  echo
  echo "A settings file .env was just created."
  echo "Add your API keys (GROQ_API_KEY, NVIDIA_API_KEY, ...) and run this file again."
  echo "See docs/providers.md for every option."
  open -t .env
  read -n 1 -s -r -p "Press any key to close..."
  echo
  exit 0
fi

echo
echo "Host starting. Keep this window open while you use the sidebar."
echo "Firefox: about:debugging -> This Firefox -> Load Temporary Add-on -> extension/manifest.json"
echo
exec .venv/bin/jev-firefox
