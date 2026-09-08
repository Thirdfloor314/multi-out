#!/usr/bin/env bash
# Install Multi-Out for the current user. No root needed.
set -euo pipefail

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SRC")"
BIN="$HOME/.local/bin"
APPS="$HOME/.local/share/applications"
UNITS="$HOME/.config/systemd/user"

for tool in pactl pipewire bluetoothctl python3; do
    command -v "$tool" >/dev/null || { echo "missing required tool: $tool" >&2; exit 1; }
done
python3 -c 'import PyQt6' 2>/dev/null || {
    echo "missing PyQt6 — install it with your package manager, e.g." >&2
    echo "  sudo dnf install python3-pyqt6      # Fedora" >&2
    echo "  sudo apt install python3-pyqt6      # Debian/Ubuntu" >&2
    exit 1
}

mkdir -p "$BIN" "$APPS" "$UNITS"
ln -sfn "$SRC/multiout" "$BIN/multiout"

sed "s|^Exec=multiout|Exec=$BIN/multiout|" "$ROOT/packaging/multiout.desktop" \
    > "$APPS/multiout.desktop"
install -m644 "$ROOT/packaging/multiout-autoswitch.service" \
    "$UNITS/multiout-autoswitch.service"

update-desktop-database "$APPS" 2>/dev/null || true
systemctl --user daemon-reload
systemctl --user enable --now multiout-autoswitch.service

echo "Installed. 'multiout' opens the window; auto-switch runs in the background."
echo "Logs: journalctl --user -u multiout-autoswitch -f"
