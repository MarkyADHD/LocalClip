# LocalClip launcher for Windows. Runs natively (no Docker/WSL): installs what's missing once, then
# starts Postgres, Redis, the backend, the worker and the web app as hidden processes and opens the app.
# Close LocalClip.cmd stops all of them. -NoBrowser is for the desktop app, which shows the app in its own window.
param([switch]$NoBrowser)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$root = $PSScriptRoot
$state = Join-Path $root ".localclip"        # tools, database, videos, logs (gitignored)
$tools = Join-Path $state "tools"
$logs = Join-Path $state "logs"
$pidFile = Join-Path $state "pids"
$url = "http://localhost:3107"
$pgPort = 5433; $redisPort = 6380             # off the defaults so old Docker installs can't clash
$pgZip = "https://get.enterprisedb.com/postgresql/postgresql-16.4-1-windows-x64-binaries.zip"
New-Item -ItemType Directory -Force $tools, $logs | Out-Null

function Test-Up { try { Invoke-WebRequest $url -UseBasicParsing -TimeoutSec 3 *> $null; $true } catch { $false } }
function Test-Cmd($name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }
function Update-Path { $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User") }
function New-Secret { $b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); -join ($b | ForEach-Object { $_.ToString("x2") }) }
# Resolves to the .exe/.cmd (not npm.ps1-style shims) and passes the array unsplatted: splatting mangles --flags.
function Invoke-Native { $exe, $rest = $args; $exe = (Get-Command $exe -CommandType Application | Select-Object -First 1).Source; & $exe $rest; if ($LASTEXITCODE -ne 0) { throw "Failed: $($args -join ' ')" } }
function Get-Zip($from, $to) {
    $zip = Join-Path $env:TEMP "localclip-download.zip"
    Write-Host "Downloading $from ..."
    $ProgressPreference = "SilentlyContinue"
    Invoke-WebRequest $from -OutFile $zip -UseBasicParsing
    New-Item -ItemType Directory -Force $to | Out-Null
    tar -xf $zip -C $to
    Remove-Item $zip
}

if (Test-Up) { if (-not $NoBrowser) { Start-Process $url }; exit }
& (Join-Path $root "Close LocalClip.ps1")   # clear out anything left half-running

# Pick up the latest LocalClip changes (harmless if offline or not a git checkout).
try { git pull --ff-only --quiet 2>$null } catch {}

# --- One-time installs -------------------------------------------------------------------------
foreach ($pkg in @(@("uv", "astral-sh.uv"), @("node", "OpenJS.NodeJS.LTS"), @("ffmpeg", "Gyan.FFmpeg"))) {
    if (-not (Test-Cmd $pkg[0])) {
        Write-Host "Installing $($pkg[0])..."
        winget install --id $pkg[1] -e --silent --accept-package-agreements --accept-source-agreements
        Update-Path
    }
}
if (-not (Test-Cmd pnpm)) { Invoke-Native npm install -g pnpm@10; Update-Path }
# The npm `claude.cmd` shim can't take multi-line arguments; the backend needs the native claude.exe.
if (-not (Test-Path "$HOME\.local\bin\claude.exe")) {
    Write-Host "Installing the native Claude Code build (uses your existing sign-in)..."
    Invoke-RestMethod https://claude.ai/install.ps1 | Invoke-Expression
}

$pgBin = Join-Path $tools "pgsql\bin"
if (-not (Test-Path "$pgBin\pg_ctl.exe")) { Get-Zip $pgZip $tools }
$redisServer = Get-ChildItem (Join-Path $tools "redis") -Recurse -Filter redis-server.exe -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $redisServer) {
    $release = Invoke-RestMethod https://api.github.com/repos/redis-windows/redis-windows/releases/latest
    $asset = $release.assets | Where-Object { $_.name -like "*Windows-x64-msys2.zip" } | Select-Object -First 1
    Get-Zip $asset.browser_download_url (Join-Path $tools "redis")
    $redisServer = Get-ChildItem (Join-Path $tools "redis") -Recurse -Filter redis-server.exe | Select-Object -First 1
}

# --- Settings ----------------------------------------------------------------------------------
if (-not (Test-Path .env)) {
    Write-Host "First run: creating .env"
    $cfg = Get-Content .env.example -Raw
    foreach ($key in "BETTER_AUTH_SECRET", "BACKEND_AUTH_SECRET", "APP_SETTINGS_ENCRYPTION_KEY", "LOCALCLIP_PASSWORD") {
        $cfg = $cfg -replace "(?m)^$key=.*$", "$key=$(New-Secret)"
    }
    Set-Content .env $cfg -NoNewline -Encoding ascii
}
if (-not (Select-String -Path .env -Pattern '^LOCALCLIP_PASSWORD=.+' -Quiet)) {
    Add-Content .env "`nLOCALCLIP_PASSWORD=$(New-Secret)" -Encoding ascii
}
foreach ($line in Get-Content .env) {
    if ($line -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$') {
        Set-Item "env:$($Matches[1])" ($Matches[2].Trim().Trim('"'))
    }
}
$dbUrl = "supoclip:supoclip_password@127.0.0.1:$pgPort/supoclip"
$env:REDIS_HOST = "127.0.0.1"; $env:REDIS_PORT = "$redisPort"; $env:REDIS_PASSWORD = ""
$env:TEMP_DIR = Join-Path $state "data"
$env:NEXT_PUBLIC_API_URL = "http://localhost:8000"
$env:NEXT_PUBLIC_APP_URL = $url; $env:BETTER_AUTH_URL = $url
$env:BACKEND_INTERNAL_URL = "http://127.0.0.1:8000"
$env:PYTHONUTF8 = "1"; $env:PYTHONUNBUFFERED = "1"
$env:NEXT_TELEMETRY_DISABLED = "1"; $env:LOCALCLIP_NATIVE = "1"
$env:npm_config_manage_package_manager_versions = "false"   # pnpm's self-switch to packageManager's version breaks on Windows
$env:PGPASSWORD = "supoclip_password"
New-Item -ItemType Directory -Force $env:TEMP_DIR | Out-Null

# --- Database and queue ------------------------------------------------------------------------
$pgData = Join-Path $state "postgres"
if (-not (Test-Path "$pgData\PG_VERSION")) {
    Write-Host "Creating the database..."
    $pw = Join-Path $state "pw.tmp"; Set-Content $pw "supoclip_password" -Encoding ascii
    Invoke-Native "$pgBin\initdb.exe" -D $pgData -U supoclip --pwfile=$pw -A scram-sha-256 -E UTF8 --locale=C
    Remove-Item $pw
    $fresh = $true
}
# Through a hidden window: Postgres keeps pg_ctl's console, and closing a visible one would stop it.
$pg = Start-Process "$pgBin\pg_ctl.exe" -WindowStyle Hidden -PassThru `
    -ArgumentList "-D `"$pgData`" -l `"$logs\postgres.log`" -o `"-p $pgPort -c listen_addresses=127.0.0.1`" -w start"
$null = $pg.Handle   # without this, ExitCode reads as empty
$pg.WaitForExit()
if ($pg.ExitCode -ne 0) { throw "Postgres didn't start; see $logs\postgres.log" }
if ($fresh) {
    Invoke-Native "$pgBin\createdb.exe" -h 127.0.0.1 -p $pgPort -U supoclip supoclip
    Invoke-Native "$pgBin\psql.exe" -h 127.0.0.1 -p $pgPort -U supoclip -d supoclip -q -v ON_ERROR_STOP=1 -f init.sql
}
$started = @()
$started += Start-Process $redisServer.FullName -ArgumentList "--port $redisPort --bind 127.0.0.1 --save `"`" --appendonly no" `
    -WindowStyle Hidden -PassThru -RedirectStandardOutput "$logs\redis.log" -RedirectStandardError "$logs\redis.err.log"

# --- Build (only when the code changed) --------------------------------------------------------
$head = git rev-parse HEAD
$builtFile = Join-Path $state "built"
if (-not (Test-Path $builtFile) -or (Get-Content $builtFile) -ne $head) {
    Write-Host "Installing and building LocalClip (first start takes a while)..."
    Push-Location backend; Invoke-Native uv sync --extra cuda; Pop-Location
    Push-Location frontend
    $env:DATABASE_URL = "postgresql://$dbUrl"
    Invoke-Native pnpm install --frozen-lockfile
    Invoke-Native pnpm run build
    Pop-Location
    Set-Content $builtFile $head
}

# --- Start the app -----------------------------------------------------------------------------
$env:DATABASE_URL = "postgresql+asyncpg://$dbUrl"
$backend = Join-Path $root "backend"
$started += Start-Process uv -WorkingDirectory $backend -WindowStyle Hidden -PassThru `
    -ArgumentList "run --no-sync uvicorn src.main:app --host 127.0.0.1 --port 8000" `
    -RedirectStandardOutput "$logs\backend.log" -RedirectStandardError "$logs\backend.err.log"
$started += Start-Process uv -WorkingDirectory $backend -WindowStyle Hidden -PassThru `
    -ArgumentList "run --no-sync arq src.workers.tasks.WorkerSettings" `
    -RedirectStandardOutput "$logs\worker.log" -RedirectStandardError "$logs\worker.err.log"
$env:DATABASE_URL = "postgresql://$dbUrl"; $env:NODE_ENV = "production"
$started += Start-Process node -WorkingDirectory (Join-Path $root "frontend") -WindowStyle Hidden -PassThru `
    -ArgumentList "node_modules\next\dist\bin\next start -p 3107 -H 127.0.0.1" `
    -RedirectStandardOutput "$logs\web.log" -RedirectStandardError "$logs\web.err.log"
Set-Content $pidFile ($started | ForEach-Object { $_.Id })

Write-Host "Waiting for $url ..."
$deadline = (Get-Date).AddMinutes(3)
while (-not (Test-Up)) {
    if ((Get-Date) -gt $deadline) { throw "LocalClip didn't come up. Logs are in $logs" }
    Start-Sleep 2
}
if (-not $NoBrowser) { Start-Process $url }
