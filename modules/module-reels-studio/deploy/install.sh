#!/bin/sh
# Installs the reels studio as a launchd agent: starts at login, restarts on a crash, keeps the Mac awake while it runs.
# The stack's secrets stay in ../../deploy/.env; this script never reads or prints them.
set -eu
here=$(cd "$(dirname "$0")/.." && pwd)
label=ru.itim.reels-studio
plist="$HOME/Library/LaunchAgents/$label.plist"
state="$HOME/.local/state/reels-studio"
mkdir -p "$state/logs" "$HOME/Library/LaunchAgents"
[ -x "$here/.venv/bin/mstudio" ] || { echo "run 'make venv' first"; exit 1; }
sed -e "s|@HERE@|$here|g" -e "s|@HOME@|$HOME|g" -e "s|@STATE@|$state|g" "$here/deploy/$label.plist.in" > "$plist"
launchctl bootout "gui/$(id -u)/$label" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$plist"
echo "installed $plist; logs: $state/logs/mstudio.log"
