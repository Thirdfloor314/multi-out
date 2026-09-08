#!/usr/bin/env bash
# Remove Multi-Out for the current user.
set -euo pipefail
systemctl --user disable --now multiout-autoswitch.service 2>/dev/null || true
rm -f "$HOME/.config/systemd/user/multiout-autoswitch.service"
rm -f "$HOME/.local/bin/multiout"
rm -f "$HOME/.local/share/applications/multiout.desktop"
systemctl --user daemon-reload 2>/dev/null || true
pkill -f "^pipewire -c .*multiout-" 2>/dev/null || true
echo "Removed. Your state file is kept at ~/.local/share/multiout/state.json"
