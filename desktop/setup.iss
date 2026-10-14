; LocalClip-Setup.exe: installs the desktop app per user (no admin), adds shortcuts and an
; Add/Remove Programs entry, then runs install.ps1 to fetch LocalClip itself and check Claude Code.
#define Version GetEnv("LOCALCLIP_VERSION")

[Setup]
AppId={{A3D0F5DB-1D9C-4E88-A70B-3696E0D1674D}
AppName=LocalClip
AppVersion={#Version}
AppPublisher=LocalClip
AppPublisherURL=https://github.com/MarkyADHD/LocalClip
DefaultDirName={localappdata}\Programs\LocalClip
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..
OutputBaseFilename=LocalClip-Setup
SetupIconFile=..\assets\localclip.ico
UninstallDisplayIcon={app}\LocalClip.exe
WizardStyle=modern
Compression=lzma2
SolidCompression=yes

[Files]
Source: "target\release\localclip.exe"; DestDir: "{app}"; DestName: "LocalClip.exe"; Flags: ignoreversion
Source: "..\install.ps1"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Icons]
Name: "{autoprograms}\LocalClip"; Filename: "{app}\LocalClip.exe"
Name: "{autodesktop}\LocalClip"; Filename: "{app}\LocalClip.exe"
Name: "{autoprograms}\Close LocalClip"; Filename: "{localappdata}\LocalClip\Close LocalClip.cmd"; IconFilename: "{app}\LocalClip.exe"

[Run]
; Visible, because the first install may ask you to sign in to Claude Code. Skipped for silent in-app updates.
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -Command ""$env:LOCALCLIP_SETUP='1'; try {{ & '{tmp}\install.ps1' } catch {{ Write-Host $_ -ForegroundColor Red; pause }"""; StatusMsg: "Downloading LocalClip..."; Check: not WizardSilent
Filename: "{app}\LocalClip.exe"; Description: "Start LocalClip"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{localappdata}\LocalClip\Close LocalClip.ps1"""; Flags: runhidden; RunOnceId: "StopLocalClip"
