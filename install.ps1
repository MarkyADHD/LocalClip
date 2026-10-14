# LocalClip installer for Windows.
#   irm https://raw.githubusercontent.com/MarkyADHD/LocalClip/main/install.ps1 | iex
# Puts LocalClip and its desktop app in %LOCALAPPDATA%\LocalClip, adds Start menu and desktop shortcuts, makes sure
# Claude Code is installed and signed in, then starts LocalClip (the first start installs the rest).
$ErrorActionPreference = "Stop"
$repo = "https://github.com/MarkyADHD/LocalClip.git"
$dir = Join-Path $env:LOCALAPPDATA "LocalClip"
function Update-Path { $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [Environment]::GetEnvironmentVariable("Path", "User") }

Write-Host "Installing LocalClip..." -ForegroundColor Cyan
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) { throw "winget is missing. Install 'App Installer' from the Microsoft Store, then run this again." }
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    winget install --id Git.Git -e --silent --accept-package-agreements --accept-source-agreements
    Update-Path
}
if (Test-Path (Join-Path $dir ".git")) { git -C $dir pull --ff-only } else { git clone --depth 1 $repo $dir }
if ($LASTEXITCODE -ne 0) { throw "Couldn't download LocalClip." }

# Clip finding runs on your Claude plan through Claude Code.
if (-not (Test-Path "$HOME\.local\bin\claude.exe")) {
    Write-Host "Installing Claude Code..."
    Invoke-RestMethod https://claude.ai/install.ps1 | Invoke-Expression
}
if (-not (Test-Path "$HOME\.claude\.credentials.json")) {
    Write-Host "`nSign in to Claude Code in the window that opens, then type /exit to come back here." -ForegroundColor Yellow
    Start-Process "$HOME\.local\bin\claude.exe" -Wait
}

# The desktop app (LocalClip.exe) opens LocalClip in its own window. If it can't be downloaded,
# the LocalClip shortcut runs LocalClip.cmd and opens it in the browser instead.
$exe = Join-Path $dir "LocalClip.exe"
try {
    $ProgressPreference = "SilentlyContinue"
    Invoke-WebRequest https://github.com/MarkyADHD/LocalClip/releases/latest/download/LocalClip.exe -OutFile $exe -UseBasicParsing
} catch { Write-Host "Couldn't download the desktop app; LocalClip will open in your browser instead." -ForegroundColor Yellow }
$start = if (Test-Path $exe) { $exe } else { Join-Path $dir "LocalClip.cmd" }

$shell = New-Object -ComObject WScript.Shell
$places = @([Environment]::GetFolderPath("Desktop"), [Environment]::GetFolderPath("Programs"))
foreach ($place in $places) {
    foreach ($name in "LocalClip", "Close LocalClip") {
        $link = $shell.CreateShortcut((Join-Path $place "$name.lnk"))
        $link.TargetPath = if ($name -eq "LocalClip") { $start } else { Join-Path $dir "$name.cmd" }
        $link.WorkingDirectory = $dir
        $link.IconLocation = Join-Path $dir "assets\localclip.ico"
        $link.Save()
    }
}

Write-Host "`nLocalClip is installed. Starting it now; the first start downloads everything and takes a while." -ForegroundColor Green
Start-Process $start -WorkingDirectory $dir
