#!/usr/bin/env bash
# Deploy a commit to the production instance.
#
#   scripts/deploy.sh [REF] [--force]        (default REF: HEAD of this tree)
#
# Production runs from its own git worktree (.prod, detached at a commit), so
# editing this tree never touches the server people are using. Deploying
# checks the worktree out at REF; the running prod server picks it up by
# itself: Vite reloads open pages, and a vite.config.js change restarts the
# server, which drops its in-memory jobs. So this refuses while a prod job is
# active, unless --force. Only committed code is deployed.

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ "$(basename "$ROOT")" = ".prod" ] && ROOT="$(dirname "$ROOT")"
PROD="$ROOT/.prod"

REF=HEAD
FORCE=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    -*) echo "usage: $0 [REF] [--force]" >&2; exit 2 ;;
    *) REF="$arg" ;;
  esac
done
COMMIT="$(git -C "$ROOT" rev-parse --verify "$REF^{commit}")"

if [ "$FORCE" != 1 ]; then
  ACTIVE="$(curl -s --max-time 3 http://127.0.0.1:5173/api/job-status \
    | "$ROOT/processing/venv/bin/python3" -c 'import json,sys; print(json.load(sys.stdin)["active"])' 2>/dev/null || echo 0)"
  if [ "$ACTIVE" != 0 ]; then
    echo "prod has $ACTIVE active job(s); wait for them or pass --force" >&2
    exit 1
  fi
fi

OLD=""
if [ -d "$PROD" ]; then
  OLD="$(git -C "$PROD" rev-parse HEAD)"
  git -C "$PROD" checkout --quiet --detach "$COMMIT"
else
  git -C "$ROOT" worktree add --quiet --detach "$PROD" "$COMMIT"
fi

# Gitignored pieces the worktree shares with the main tree
for d in processing/venv processing/models; do
  [ -e "$PROD/$d" ] || ln -s "$ROOT/$d" "$PROD/$d"
done

if [ ! -d "$PROD/web/node_modules" ] || { [ -n "$OLD" ] && \
    ! git -C "$PROD" diff --quiet "$OLD" "$COMMIT" -- web/package.json web/pnpm-lock.yaml; }; then
  eval "$(fnm env --use-on-cd)"
  corepack enable
  (cd "$PROD/web" && pnpm install --frozen-lockfile)
fi

echo "prod now at $(git -C "$PROD" log --oneline -1)"
if [ -n "$OLD" ] && [ "$OLD" != "$COMMIT" ]; then
  git -C "$PROD" diff --stat "$OLD" "$COMMIT"
fi
