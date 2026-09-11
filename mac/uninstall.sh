#!/usr/bin/env bash
# Remove Multi-Out for the current user on macOS.
set -euo pipefail
LABEL="com.user.multiout-autoswitch"
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
rm -f "$HOME/Library/LaunchAgents/$LABEL.plist"
rm -f "$HOME/.local/bin/multiout"
echo "Removed. Your state file is kept at"
echo "  ~/Library/Application Support/Multi-Out/state.json"
