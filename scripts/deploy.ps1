# Deploy a commit to the production instance.
#
#   scripts\deploy.cmd [REF] [--force]        (default REF: HEAD of this tree)
#
# Production runs from its own git worktree (.prod, detached at a commit), so
# editing this tree never touches the server people are using. Deploying
# checks the worktree out at REF; the running prod server picks it up by
# itself: Vite reloads open pages, and a vite.config.js change restarts the
# server, which drops its in-memory jobs. So this refuses while a prod job is
# active, unless --force. Only committed code is deployed.

. "$PSScriptRoot\common.ps1"
$Prod = "$Root\.prod"

$Ref = "HEAD"
$Force = $false
foreach ($arg in $args) {
  if ($arg -eq "--force") { $Force = $true }
  elseif ($arg -like "-*") { Write-Host "usage: scripts\deploy.cmd [REF] [--force]"; exit 2 }
  else { $Ref = $arg }
}
$Commit = git -C $Root rev-parse --verify "$Ref^{commit}"
if ($LASTEXITCODE -ne 0) { exit 1 }

if (-not $Force) {
  [System.Net.WebRequest]::DefaultWebProxy = $null
  $Active = 0
  try { $Active = (Invoke-RestMethod -Uri http://127.0.0.1:5173/api/job-status -TimeoutSec 3).active } catch {}
  if ($Active -ne 0) {
    Write-Host "prod has $Active active job(s); wait for them or pass --force"
    exit 1
  }
}

$Old = ""
if (Test-Path -LiteralPath $Prod) {
  $Old = git -C $Prod rev-parse HEAD
  git -C $Prod checkout --quiet --detach $Commit
} else {
  git -C $Root worktree add --quiet --detach $Prod $Commit
}
if ($LASTEXITCODE -ne 0) { exit 1 }

# Gitignored pieces the worktree shares with the main tree. Junctions: unlike
# symlinks they need neither an elevated terminal nor Developer Mode.
# (Remove-Item -Recurse on .prod would follow them; use `git worktree remove`.)
foreach ($d in "processing\venv", "processing\models") {
  if (-not (Test-Path -LiteralPath "$Prod\$d")) {
    New-Item -ItemType Directory -Force "$Root\$d" -ErrorAction Stop | Out-Null
    New-Item -ItemType Junction -Path "$Prod\$d" -Target "$Root\$d" -ErrorAction Stop | Out-Null
  }
}

$Install = -not (Test-Path -LiteralPath "$Prod\web\node_modules")
if ($Old) {
  git -C $Prod diff --quiet $Old $Commit -- web/package.json web/pnpm-lock.yaml
  if ($LASTEXITCODE -ne 0) { $Install = $true }
}
if ($Install) {
  Use-Node "$Prod\web"
  Install-WebPackages "$Prod\web"
}

Write-Host "prod now at $(git -C $Prod log --oneline -1)"
if ($Old -and $Old -ne $Commit) {
  git -C $Prod diff --stat $Old $Commit
}
exit 0
