#!/usr/bin/env bash
# Install Multi-Out for the current user on macOS. No root needed.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SRC")"
BIN="$HOME/.local/bin"
AGENTS="$HOME/Library/LaunchAgents"
LOGS="$HOME/Library/Logs"
LABEL="com.user.multiout-autoswitch"

command -v python3 >/dev/null || { echo "missing required tool: python3" >&2; exit 1; }
python3 -c 'import PyQt6' 2>/dev/null || {
    echo "missing PyQt6 — install it with:" >&2
    echo "  pip3 install PyQt6" >&2
    exit 1
}
python3 -c 'import objc' 2>/dev/null || {
    echo "missing PyObjC — install it with:" >&2
    echo "  pip3 install pyobjc-core pyobjc-framework-Cocoa" >&2
    exit 1
}

mkdir -p "$BIN" "$AGENTS" "$LOGS"
ln -sfn "$SRC/multiout" "$BIN/multiout"

PY="$(command -v python3)"
sed -e "s#__HOME__#$HOME#g" \
    -e "s#__PYTHON__#$PY#g" \
    -e "s#__MULTIOUT__#$BIN/multiout#g" \
    "$ROOT/packaging/multiout-autoswitch.plist" \
    > "$AGENTS/$LABEL.plist"

# Reload cleanly whether or not a previous copy was loaded.
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$AGENTS/$LABEL.plist"

echo "Installed. '$BIN/multiout' opens the window; auto-switch runs in the background."
echo "Logs: tail -f ~/Library/Logs/multiout-autoswitch.log"
