# One-time local setup on Windows. From the repo root:
#   powershell -ExecutionPolicy Bypass -File scripts\setup-local.ps1
# Safe to re-run. Stop running dev servers first (npm can't replace locked binaries on Windows).
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

function Require($cmd, $hint) {
  if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "$cmd not found. $hint" }
}
Require git 'Install Git: https://git-scm.com/downloads'
Require node 'Install Node.js 22 LTS: https://nodejs.org'

Write-Host '== Python virtual environment (.venv)' -ForegroundColor Cyan
if (-not (Test-Path .venv\Scripts\python.exe)) {
  if (Get-Command py -ErrorAction SilentlyContinue) { py -3.13 -m venv .venv }
  elseif (Get-Command python -ErrorAction SilentlyContinue) { python -m venv .venv }
  else { throw 'Install Python 3.13: https://www.python.org/downloads/ (tick "Add python.exe to PATH")' }
}
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
if ($LASTEXITCODE) { throw 'pip install failed' }

Write-Host '== backend\.env' -ForegroundColor Cyan
if (Test-Path backend\.env) {
  Write-Host 'backend\.env already exists - left unchanged.'
} else {
  $bytes = New-Object byte[] 32
  [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
  $secret = -join ($bytes | ForEach-Object { $_.ToString('x2') })
  (Get-Content .env.example) -replace '^JWT_SECRET=.*', "JWT_SECRET=$secret" | Set-Content backend\.env
  Write-Host 'Created backend\.env with a random JWT_SECRET. Add your API keys to it (see setup.md).' -ForegroundColor Yellow
}

Write-Host '== Frontend packages' -ForegroundColor Cyan
Push-Location frontend
try {
  npm install
  if ($LASTEXITCODE) { throw 'npm install failed' }
  npx playwright install chromium
  if ($LASTEXITCODE) { throw 'Playwright browser install failed' }
} finally { Pop-Location }

Write-Host ''
Write-Host 'Done. Start the app with:  powershell -ExecutionPolicy Bypass -File scripts\dev.ps1' -ForegroundColor Green
