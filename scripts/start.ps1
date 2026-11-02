# Start a Werewolf Viewer server in the background (persists after terminal close).
#
#   scripts\start.cmd [prod|dev]        (default: prod)
#
# prod  http://<host>:5173/  code from the .prod worktree, pinned to a commit
#       (update it with scripts\deploy.cmd), library videos\
# dev   http://<host>:5174/  code from this working tree (edits hot-reload),
#       library videos-dev\ (fill it with scripts\dev-library.cmd)
#
# Both listen on the LAN. Logs and PIDs: .run\<instance>.log, .run\<instance>.pid

$ErrorActionPreference = "Stop"
. "$PSScriptRoot\common.ps1"

$Instance = if ($args.Count -gt 0) { $args[0] } else { "prod" }
switch ($Instance) {
  "prod" { $Code = "$Root\.prod"; $Videos = "$Root\videos"; $Port = 5173 }
  "dev"  { $Code = $Root; $Videos = "$Root\videos-dev"; $Port = 5174 }
  default { Write-Host "usage: scripts\start.cmd [prod|dev]"; exit 2 }
}

$RunDir = "$Root\.run"
$PidFile = "$RunDir\$Instance.pid"
$LogFile = "$RunDir\$Instance.log"
New-Item -ItemType Directory -Force $RunDir, $Videos | Out-Null

if (Get-ServerProcess $PidFile) {
  Write-Host "$Instance server is already running (PID $(Get-Content -LiteralPath $PidFile -TotalCount 1))"
  Write-Host "Log: $LogFile"
  exit 0
}

# First start of prod: create its worktree at this tree's HEAD
if ($Instance -eq "prod" -and -not (Test-Path -LiteralPath $Code)) {
  & "$PSScriptRoot\deploy.ps1"
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

$Web = "$Code\web"
Use-Node $Web
if (-not (Test-Path -LiteralPath "$Web\node_modules")) { Install-WebPackages $Web }

# Start server in the background: its own hidden console, so closing this
# terminal doesn't end it (cmd only for the log redirection)
$env:WEREWOLF_VIDEOS_DIR = $Videos
$env:VITE_INSTANCE = $Instance
$Node = (Get-Command node).Source
$Line = "/d /c `"`"$Node`" `"$Web\node_modules\vite\bin\vite.js`" --host 0.0.0.0 --port $Port --strictPort > `"$LogFile`" 2>&1`""
$Proc = Start-Process -FilePath $env:ComSpec -ArgumentList $Line -WorkingDirectory $Web -WindowStyle Hidden -PassThru
Set-Content -LiteralPath $PidFile -Value $Proc.Id -Encoding ascii

# A failed start (say, the port is taken) would otherwise go unnoticed
$Deadline = (Get-Date).AddSeconds(20)
$Up = $false
while (-not $Up -and -not $Proc.HasExited -and (Get-Date) -lt $Deadline) {
  Start-Sleep -Milliseconds 300
  $Client = New-Object System.Net.Sockets.TcpClient
  try { $Client.Connect("127.0.0.1", $Port); $Up = $true } catch {} finally { $Client.Close() }
}
if ($Proc.HasExited) {
  Remove-Item -LiteralPath $PidFile -ErrorAction SilentlyContinue
  Write-Host "$Instance server failed to start:"
  Get-Content -LiteralPath $LogFile -Tail 15 | ForEach-Object { Write-Host "  $_" }
  exit 1
}

Write-Host "$Instance server started (PID $($Proc.Id))"
Write-Host "Code: $Code"
Write-Host "Library: $Videos"
Write-Host "Log: $LogFile"
Write-Host "URL: http://localhost:$Port/"
