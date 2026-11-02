# Put games from the production library (videos\) into the dev library (videos-dev\).
#
#   scripts\dev-library.cmd VIDEO_ID...      add (or refresh) these games
#   scripts\dev-library.cmd --all            every analysed game in videos\
#
# video.mp4 is hard-linked (no extra disk, and deleting it in dev leaves the
# production copy alone); info.json and metadata.json are copied, so dev
# analyses and edits never change what production shows. Bookmarks and resume
# points (viewer_state.json) are not copied.

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\common.ps1"
$Src = "$Root\videos"
$Dst = "$Root\videos-dev"

$Ids = @($args)
if ($Ids.Count -eq 1 -and $Ids[0] -eq "--all") {
  $Ids = @(Get-ChildItem $Src -Directory | Where-Object { Test-Path "$($_.FullName)\metadata.json" } | ForEach-Object { $_.Name })
}
if ($Ids.Count -eq 0) { Write-Host "usage: scripts\dev-library.cmd VIDEO_ID... | --all"; exit 2 }

foreach ($id in $Ids) {
  # -LiteralPath throughout: nothing about a video ID should act as a wildcard
  if (-not (Test-Path -LiteralPath "$Src\$id\video.mp4")) {
    Write-Host "skip ${id}: no $Src\$id\video.mp4"
    continue
  }
  New-Item -ItemType Directory -Force "$Dst\$id" | Out-Null
  if (Test-Path -LiteralPath "$Dst\$id\video.mp4") { Remove-Item -LiteralPath "$Dst\$id\video.mp4" -Force }
  New-Item -ItemType HardLink -Path "$Dst\$id\video.mp4" -Target "$Src\$id\video.mp4" | Out-Null
  foreach ($f in "info.json", "metadata.json") {
    if (Test-Path -LiteralPath "$Src\$id\$f") { Copy-Item -LiteralPath "$Src\$id\$f" "$Dst\$id\$f" -Force }
  }
  Write-Host "dev library: $id"
}
