#!/bin/bash
# Double-click this file to start Property Helper on a Mac.
# The first time: right-click it, choose Open, then press Open again.
# Keep this window open while you use Property Helper. Close it to stop.
cd "$(dirname "$0")" || exit 1

# The app prints its own plain lines ("Starting Property Helper.") and keeps the technical log in a file.
export PROPHELPER_QUIET=1
export UV_NO_PROGRESS=1

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

problem() {
  echo
  echo "Something went wrong. Nothing was lost, and your places are safe."
  echo "$1"
  echo "Your places are kept in a folder of their own, so downloading a newer copy of this app is safe too."
  echo "Press Return to close this window."
  read -r _
  exit 1
}

if ! command -v uv >/dev/null 2>&1; then
  echo "First time setup: installing a small helper called uv. This needs internet and takes about a minute."
  curl -LsSf https://astral.sh/uv/install.sh | sh || problem "Step 1 of 2 (installing the helper called uv) failed. Check your internet connection and try again."
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  command -v uv >/dev/null 2>&1 || problem "Step 1 of 2 (installing the helper called uv) finished but the helper could not be found. Close this window and double-click again."
fi

echo "Property Helper is starting. Keep this window open while you use it. Close it to stop."
if [ ! -d .venv ]; then
  echo "The first time can take about a minute while it sets itself up. Please wait."
fi
echo "When it says \"Property Helper is running\", your browser opens by itself."
uv run --quiet prophelper || problem "Step 2 of 2 (starting the app) stopped with a problem. Double-click again to try once more."
echo
echo "Property Helper has stopped. You can close this window."
