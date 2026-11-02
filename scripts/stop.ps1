# Stop a Werewolf Viewer server.
#
#   scripts\stop.cmd [prod|dev]        (default: prod)
#
# This ends the server's whole process tree, including any running download or
# analysis (unlike macOS, where those run detached and keep going); check
# /api/job-status before stopping prod. A stopped download resumes from its
# partial file when it is started again.

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\common.ps1"

$Instance = if ($args.Count -gt 0) { $args[0] } else { "prod" }
if ($Instance -notin "prod", "dev") { Write-Host "usage: scripts\stop.cmd [prod|dev]"; exit 2 }
$PidFile = "$Root\.run\$Instance.pid"

if (-not (Test-Path -LiteralPath $PidFile)) {
  Write-Host "No $Instance server PID file found"
  exit 0
}

$Server = Get-ServerProcess $PidFile
$Id = (Get-Content -LiteralPath $PidFile -TotalCount 1).Trim()
Remove-Item -LiteralPath $PidFile
if ($Server) {
  taskkill /PID $Id /T /F | Out-Null
  Write-Host "$Instance server stopped (PID $Id)"
} else {
  Write-Host "$Instance server was not running (stale PID file cleaned up)"
}
