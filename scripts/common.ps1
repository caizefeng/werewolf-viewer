# Shared by the Windows scripts (dot-sourced): the main tree, Node.js on PATH,
# and the instance's server process.
# Keep these .ps1 files ASCII: Windows PowerShell reads a file without a BOM in
# the ANSI code page.

$Root = Split-Path -Parent $PSScriptRoot
# Called as .prod\scripts\start.cmd: the instances still belong to the main tree
if ((Split-Path -Leaf $Root) -eq ".prod") { $Root = Split-Path -Parent $Root }

# Node for web\.node-version when fnm is installed, otherwise the node on PATH.
function Use-Node($WebDir) {
  if (Get-Command fnm -ErrorAction SilentlyContinue) {
    fnm env --shell powershell | Out-String | Invoke-Expression
    Push-Location $WebDir
    fnm use --install-if-missing --silent-if-unchanged
    Pop-Location
  }
  if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js not found. Install it with: winget install Schniz.fnm  (see the README's Windows setup)"
  }
}

# corepack instead of its pnpm shim: `corepack enable` needs an elevated
# terminal when Node lives under Program Files. Node 25+ has no corepack.
function Install-WebPackages($WebDir) {
  $env:COREPACK_ENABLE_DOWNLOAD_PROMPT = "0"
  Push-Location $WebDir
  if (Get-Command corepack -ErrorAction SilentlyContinue) {
    corepack pnpm install --frozen-lockfile
  } elseif (Get-Command pnpm -ErrorAction SilentlyContinue) {
    pnpm install --frozen-lockfile
  } else {
    Pop-Location
    throw "Neither corepack nor pnpm found. Install fnm (winget install Schniz.fnm) or pnpm (npm install -g pnpm)"
  }
  $code = $LASTEXITCODE
  Pop-Location
  if ($code -ne 0) { throw "pnpm install failed (exit $code)" }
}

# The instance's running server, or $null. PIDs get reused quickly on Windows,
# so a recorded PID only counts if that process really is our server.
function Get-ServerProcess($PidFile) {
  if (-not (Test-Path -LiteralPath $PidFile)) { return $null }
  $id = (Get-Content -LiteralPath $PidFile -TotalCount 1).Trim()
  $proc = Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue
  if ($proc -and $proc.CommandLine -match "vite\.js") { return $proc }
  return $null
}
