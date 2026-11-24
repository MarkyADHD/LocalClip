# CI check for the Windows launcher scripts, run on Windows PowerShell 5.1 (what users have).
# A syntax error in LocalClip.ps1 would stop every install from starting, and Linux CI can't see one.
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot
foreach ($name in "LocalClip.ps1", "Close LocalClip.ps1", "install.ps1") {
    $errs = $null
    [void][System.Management.Automation.Language.Parser]::ParseFile((Join-Path $root $name), [ref]$null, [ref]$errs)
    if ($errs) { throw "$name does not parse: $($errs[0].Message) (line $($errs[0].Extent.StartLineNumber))" }
}

# The log-keeping block, lifted out of the launcher and run for 7 launches in a scratch folder.
$block = [regex]::Match((Get-Content -Raw (Join-Path $root "LocalClip.ps1")), '(?s)try \{\s+\$oldLogs.*?\} catch \{[^\n]*\}').Value
if (-not $block) { throw "Log-keeping block not found in LocalClip.ps1" }
$logs = Join-Path $env:TEMP "localclip-launcher-check"
Remove-Item $logs -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $logs | Out-Null
1..7 | ForEach-Object {
    Set-Content "$logs\worker.err.log" "run $_"; Set-Content "$logs\backend.log" $null
    Set-Content "$logs\postgres.log" "pg"
    $held = [IO.File]::Open("$logs\launcher.log", "Create", "Write", "None")   # the desktop app holds this one open
    try { Invoke-Expression $block } finally { $held.Close() }
    Start-Sleep -Milliseconds 1100
}
$left = (Get-ChildItem $logs -File).Name -join ","
if ($left -ne "launcher.log,postgres.log") { throw "Unexpected files left in logs: $left" }
$runs = @(Get-ChildItem "$logs\old" -Directory | Sort-Object Name -Descending)
if ($runs.Count -ne 5) { throw "Expected 5 old runs, found $($runs.Count)" }
if ((Get-Content "$($runs[0].FullName)\worker.err.log") -ne "run 7") { throw "Newest old run is not the last launch" }
"Launcher scripts parse and old logs are kept."
