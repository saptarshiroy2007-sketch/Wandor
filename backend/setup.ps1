# Run once from inside the backend/ folder:  powershell -ExecutionPolicy Bypass -File setup.ps1
# Creates venv, installs deps, and writes .env by asking you for the 2 required values.

Write-Host "Creating virtual environment..." -ForegroundColor Cyan
python -m venv .venv

Write-Host "Activating venv and installing requirements..." -ForegroundColor Cyan
& .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

if (-Not (Test-Path ".env")) {
    Write-Host ""
    Write-Host "No .env found. Enter your values (paste and hit Enter):" -ForegroundColor Yellow
    $dbUrl = Read-Host "DATABASE_URL (Supabase pooler connection string)"
    $jwtSecret = Read-Host "JWT_SECRET (any long random string - press Enter to auto-generate)"
    if ([string]::IsNullOrWhiteSpace($jwtSecret)) {
        $jwtSecret = [System.Guid]::NewGuid().ToString() + [System.Guid]::NewGuid().ToString()
    }
    "DATABASE_URL=$dbUrl`nJWT_SECRET=$jwtSecret" | Out-File -FilePath ".env" -Encoding utf8
    Write-Host ".env created." -ForegroundColor Green
} else {
    Write-Host ".env already exists, leaving it alone." -ForegroundColor Green
}

Write-Host ""
Write-Host "Setup complete. Run the server with:" -ForegroundColor Cyan
Write-Host "  .venv\Scripts\activate" -ForegroundColor White
Write-Host "  uvicorn app.main:app --reload" -ForegroundColor White
