#!/usr/bin/env bash
# Put games from the production library (videos/) into the dev library (videos-dev/).
#
#   scripts/dev-library.sh VIDEO_ID...      add (or refresh) these games
#   scripts/dev-library.sh --all            every analysed game in videos/
#
# video.mp4 is hard-linked (no extra disk, and deleting it in dev leaves the
# production copy alone); info.json and metadata.json are copied, so dev
# analyses and edits never change what production shows. Bookmarks and resume
# points (viewer_state.json) are not copied.

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ "$(basename "$ROOT")" = ".prod" ] && ROOT="$(dirname "$ROOT")"
SRC="$ROOT/videos"
DST="$ROOT/videos-dev"

if [ "$1" = "--all" ]; then
  set -- $(cd "$SRC" && for d in */; do [ -f "$d/metadata.json" ] && echo "${d%/}"; done)
fi
[ $# -gt 0 ] || { echo "usage: $0 VIDEO_ID... | --all" >&2; exit 2; }

for id in "$@"; do
  if [ ! -f "$SRC/$id/video.mp4" ]; then
    echo "skip $id: no $SRC/$id/video.mp4" >&2
    continue
  fi
  mkdir -p "$DST/$id"
  ln -f "$SRC/$id/video.mp4" "$DST/$id/video.mp4"
  for f in info.json metadata.json; do
    [ -f "$SRC/$id/$f" ] && cp "$SRC/$id/$f" "$DST/$id/$f"
  done
  echo "dev library: $id"
done
