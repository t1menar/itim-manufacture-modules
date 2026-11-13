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
domain="gui/$(id -u)"
launchctl bootout "$domain/$label" 2>/dev/null || true
# bootout returns before the old process is gone; bootstrap fails (error 5) until then
i=0
while launchctl print "$domain/$label" >/dev/null 2>&1 && [ $i -lt 30 ]; do sleep 1; i=$((i + 1)); done
i=0
until launchctl bootstrap "$domain" "$plist" 2>/dev/null; do
  i=$((i + 1))
  [ $i -ge 10 ] && { echo "launchctl bootstrap failed; see: launchctl print $domain/$label"; exit 1; }
  sleep 2
done
sleep 3
launchctl print "$domain/$label" >/dev/null 2>&1 || { echo "the agent is not loaded"; exit 1; }
echo "installed $plist; logs: $state/logs/mstudio.log"
