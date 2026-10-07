# Runs the same checks as CI. Stops at the first failure. From the repo root:
#   powershell -ExecutionPolicy Bypass -File scripts\check.ps1
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$env:PYTHONPATH = "$root\backend"
$env:DATABASE_URL = ''

function Step($name, [scriptblock]$run) {
  Write-Host "== $name" -ForegroundColor Cyan
  $global:LASTEXITCODE = 0
  & $run
  if ($LASTEXITCODE) { throw "$name failed" }
}

Step 'Backend tests' { .\.venv\Scripts\python.exe -m unittest discover -s backend/tests -q }
Step 'Backend compile' { .\.venv\Scripts\python.exe -m compileall -q backend }
Push-Location frontend
try {
  Step 'Lint' { npm run lint }
  Step 'Unit tests' { npm test }
  Step 'Build' { npm run build }
  Step 'Browser tests' { npm run test:e2e }
  Step 'Dependency audit' { npm audit --audit-level=high }
} finally { Pop-Location }
Step 'Whitespace' { git diff --check }
Write-Host 'All checks passed.' -ForegroundColor Green
