#!/usr/bin/env bash
# Start the Werewolf Viewer server in the background.
# The server persists after terminal close. Logs go to .run/server.log.

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNDIR="$ROOT/.run"
PIDFILE="$RUNDIR/server.pid"
LOGFILE="$RUNDIR/server.log"

mkdir -p "$RUNDIR"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "Server is already running (PID $(cat "$PIDFILE"))"
  echo "Log: $LOGFILE"
  exit 0
fi

# Load fnm and corepack
eval "$(fnm env --use-on-cd)"
corepack enable

cd "$ROOT/web"

# Start server in background, immune to terminal close
nohup pnpm dev > "$LOGFILE" 2>&1 &
echo $! > "$PIDFILE"

echo "Server started (PID $!)"
echo "Log: $LOGFILE"
echo "URL: http://localhost:5173/"
