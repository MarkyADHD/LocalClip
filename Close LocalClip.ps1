# Stops everything LocalClip.ps1 started: web app, backend, worker, Redis and Postgres.
$ErrorActionPreference = "SilentlyContinue"
$state = Join-Path $PSScriptRoot ".localclip"
foreach ($id in Get-Content (Join-Path $state "pids")) { taskkill /PID $id /T /F *> $null }
Remove-Item (Join-Path $state "pids")
$pgCtl = Join-Path $state "tools\pgsql\bin\pg_ctl.exe"
if (Test-Path $pgCtl) { & $pgCtl -D (Join-Path $state "postgres") stop -m fast *> $null }
