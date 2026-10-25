#!/usr/bin/env bash
# Start a Werewolf Viewer server in the background (persists after terminal close).
#
#   scripts/start.sh [prod|dev]        (default: prod)
#
# prod  http://<host>:5173/  code from the .prod worktree, pinned to a commit
#       (update it with scripts/deploy.sh), library videos/
# dev   http://<host>:5174/  code from this working tree (edits hot-reload),
#       library videos-dev/ (fill it with scripts/dev-library.sh)
#
# Both listen on the LAN. Logs and PIDs: .run/<instance>.log, .run/<instance>.pid

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Called as .prod/scripts/start.sh: the instances still belong to the main tree
[ "$(basename "$ROOT")" = ".prod" ] && ROOT="$(dirname "$ROOT")"

INSTANCE="${1:-prod}"
case "$INSTANCE" in
  prod) CODE="$ROOT/.prod"; VIDEOS="$ROOT/videos"; PORT=5173 ;;
  dev)  CODE="$ROOT";       VIDEOS="$ROOT/videos-dev"; PORT=5174 ;;
  *) echo "usage: $0 [prod|dev]" >&2; exit 2 ;;
esac

RUNDIR="$ROOT/.run"
PIDFILE="$RUNDIR/$INSTANCE.pid"
LOGFILE="$RUNDIR/$INSTANCE.log"
mkdir -p "$RUNDIR" "$VIDEOS"

if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "$INSTANCE server is already running (PID $(cat "$PIDFILE"))"
  echo "Log: $LOGFILE"
  exit 0
fi

# First start of prod: create its worktree at this tree's HEAD
if [ "$INSTANCE" = prod ] && [ ! -d "$CODE" ]; then
  "$ROOT/scripts/deploy.sh"
fi

# Load fnm and corepack
eval "$(fnm env --use-on-cd)"
corepack enable

cd "$CODE/web"
[ -d node_modules ] || pnpm install --frozen-lockfile

# Start server in background, immune to terminal close
WEREWOLF_VIDEOS_DIR="$VIDEOS" VITE_INSTANCE="$INSTANCE" \
  nohup pnpm exec vite --host 0.0.0.0 --port "$PORT" --strictPort > "$LOGFILE" 2>&1 &
echo $! > "$PIDFILE"

echo "$INSTANCE server started (PID $!)"
echo "Code: $CODE"
echo "Library: $VIDEOS"
echo "Log: $LOGFILE"
echo "URL: http://localhost:$PORT/"
