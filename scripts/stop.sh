#!/usr/bin/env bash
# Stop a Werewolf Viewer server.
#
#   scripts/stop.sh [prod|dev]        (default: prod)
#
# Download/analysis processes run detached and keep going, but the restarted
# server no longer tracks them; check /api/job-status before stopping prod.

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ "$(basename "$ROOT")" = ".prod" ] && ROOT="$(dirname "$ROOT")"

INSTANCE="${1:-prod}"
case "$INSTANCE" in
  prod|dev) ;;
  *) echo "usage: $0 [prod|dev]" >&2; exit 2 ;;
esac
PIDFILE="$ROOT/.run/$INSTANCE.pid"

if [ ! -f "$PIDFILE" ]; then
  echo "No $INSTANCE server PID file found"
  exit 0
fi

PID=$(cat "$PIDFILE")

if kill -0 "$PID" 2>/dev/null; then
  # Kill the process tree (pnpm spawns child processes)
  pkill -P "$PID" 2>/dev/null
  kill "$PID" 2>/dev/null
  rm -f "$PIDFILE"
  echo "$INSTANCE server stopped (PID $PID)"
else
  rm -f "$PIDFILE"
  echo "$INSTANCE server was not running (stale PID file cleaned up)"
fi
