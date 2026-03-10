#!/usr/bin/env bash
# Stop the Werewolf Viewer server.

DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="$DIR/.server.pid"

if [ ! -f "$PIDFILE" ]; then
  echo "No server PID file found"
  exit 0
fi

PID=$(cat "$PIDFILE")

if kill -0 "$PID" 2>/dev/null; then
  # Kill the process tree (pnpm spawns child processes)
  pkill -P "$PID" 2>/dev/null
  kill "$PID" 2>/dev/null
  rm -f "$PIDFILE"
  echo "Server stopped (PID $PID)"
else
  rm -f "$PIDFILE"
  echo "Server was not running (stale PID file cleaned up)"
fi
