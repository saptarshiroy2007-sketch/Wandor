# Runs backend (uvicorn) + webapp (vite) together. Ctrl+C stops both.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# --- pick a Python version with prebuilt wheel support (3.12/3.11/3.13 are safest;
# 3.14 is too new - some pinned deps here (pydantic-core) have no wheel for it yet
# and fall back to compiling Rust/C, which needs Visual Studio Build Tools most
# people don't have installed) ---
$pythonCmd = $null
foreach ($v in @("-3.12", "-3.11", "-3.13")) {
  try {
    py $v --version *> $null
    if ($LASTEXITCODE -eq 0) { $pythonCmd = @("py", $v); break }
  } catch {}
}
if (-not $pythonCmd) {
  Write-Host "No Python 3.11/3.12/3.13 found via 'py' - falling back to 'python' on PATH." -ForegroundColor Yellow
  Write-Host "If that's 3.14, dependency install will likely fail (see below)." -ForegroundColor Yellow
  $pythonCmd = @("python")
}
Write-Host "Using: $($pythonCmd -join ' ')"

# --- backend deps (installed straight to this Python, no venv - avoids the
# slow/hanging `ensurepip` step some Python installs hit on Windows) ---
Write-Host "Checking backend deps..."
& $pythonCmd[0] $pythonCmd[1..($pythonCmd.Length-1)] -m pip install -r backend\requirements.txt
if ($LASTEXITCODE -ne 0) {
  Write-Host ""
  Write-Host "pip install failed (see errors above)." -ForegroundColor Red
  Write-Host "Common cause: no Python 3.11/3.12/3.13 installed, so this fell back to" -ForegroundColor Yellow
  Write-Host "a newer Python lacking prebuilt wheels for some pinned packages here." -ForegroundColor Yellow
  Write-Host "Install Python 3.12 (winget install Python.Python.3.12) and re-run." -ForegroundColor Yellow
  exit 1
}

if (-not (Test-Path "backend\.env")) {
  Copy-Item backend\.env.example backend\.env
}

# --- webapp deps ---
if (-not (Test-Path "webapp\node_modules")) {
  Write-Host "Installing webapp deps..."
  Push-Location webapp
  npm install
  Pop-Location
}
if (-not (Test-Path "webapp\.env")) {
  "VITE_API_BASE_URL=http://localhost:8000" | Out-File -Encoding utf8 webapp\.env
}

# --- run both ---
$backendArgs = $pythonCmd[1..($pythonCmd.Length-1)] + @("-m", "uvicorn", "app.main:app", "--reload", "--host", "0.0.0.0", "--port", "8000")
$backend = Start-Process -FilePath $pythonCmd[0] `
  -ArgumentList $backendArgs `
  -WorkingDirectory "backend" -PassThru -NoNewWindow

$frontend = Start-Process -FilePath "npm.cmd" `
  -ArgumentList "run dev -- --host 0.0.0.0 --port 5173" `
  -WorkingDirectory "webapp" -PassThru -NoNewWindow

Write-Host "Backend  -> http://localhost:8000"
Write-Host "Frontend -> http://localhost:5173"
Write-Host "Press Ctrl+C to stop both."

try {
  Wait-Process -Id $backend.Id, $frontend.Id
} finally {
  Write-Host "Stopping..."
  Stop-Process -Id $backend.Id -Force -ErrorAction SilentlyContinue
  Stop-Process -Id $frontend.Id -Force -ErrorAction SilentlyContinue
}
