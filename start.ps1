# ── tech-atlas · DEV (Windows) ────────────────────────────────────────────
# Creates the venv if missing, installs requirements, prepares the
# database, and starts the API with auto-reload on http://127.0.0.1:8100
# (override with $env:PORT). Windows equivalent of start.sh.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Fail($msg) { Write-Host "error: $msg" -ForegroundColor Red; exit 1 }

# 1. Virtual env (Python 3.12+)
if (-not (Test-Path ".venv")) {
  $created = $false
  if (Get-Command uv -ErrorAction SilentlyContinue) {
    uv venv --seed --python 3.12
    if ($LASTEXITCODE -eq 0) { $created = $true }
  }
  if (-not $created -and (Get-Command py -ErrorAction SilentlyContinue)) {
    foreach ($ver in "-3.12", "-3.13") {
      & py $ver -m venv .venv 2>$null
      if ($LASTEXITCODE -eq 0) { $created = $true; break }
    }
  }
  if (-not $created -and (Get-Command python -ErrorAction SilentlyContinue)) {
    & python -c "import sys; sys.exit(0 if sys.version_info >= (3,12) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) {
      & python -m venv .venv
      if ($LASTEXITCODE -eq 0) { $created = $true }
    }
  }
  if (-not $created) {
    Fail "need Python 3.12+ — install from https://python.org and tick 'Add python.exe to PATH'"
  }
}

# 2. Install into the venv (no activation needed — call its python directly)
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
function Run { & $py @args; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE } }
Run -m pip install --quiet -r requirements.txt
Run -m pip install --quiet -e .

# 3. Headless browser for the crawler (idempotent, fast when present)
& $py -m playwright install chromium *> $null
if ($LASTEXITCODE -ne 0) {
  Write-Host "warning: playwright chromium install failed — JS-heavy sources degrade to plain HTTP"
}

# 4. .env
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env" }

# 5. Database: create collections/indexes and seed sources + prompts
Run scripts\create_db.py
Run scripts\seed_sources.py
Run scripts\seed_prompts.py
Run scripts\seed_scoring.py

# 6. Serve (dev: auto-reload; host/port in main.py, PORT env overrides)
Run main.py
