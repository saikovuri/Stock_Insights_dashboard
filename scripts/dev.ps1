# Starts the backend (port 8000) and frontend (port 5173) in two new windows. From the repo root:
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1
# Close a window (or press Ctrl+C in it) to stop that server.
$root = Split-Path $PSScriptRoot -Parent
$shell = if (Get-Command pwsh -ErrorAction SilentlyContinue) { 'pwsh' } else { 'powershell' }
Start-Process $shell -ArgumentList '-NoExit', '-Command', "Set-Location '$root\backend'; ..\.venv\Scripts\python.exe -m uvicorn main:app --port 8000 --reload"
Start-Process $shell -ArgumentList '-NoExit', '-Command', "Set-Location '$root\frontend'; npm run dev"
Write-Host 'Backend:  http://localhost:8000/api/health'
Write-Host 'App:      http://localhost:5173'
