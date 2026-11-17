; Inno Setup script for the CCGuard installer.
; Build with: python tools/build_windows.py --installer   (passes /DAppVersion and /DSourceDir)
; Per-user install, no administrator rights; the uninstaller removes the program, its shortcuts and
; the optional autostart entry, and keeps the user's monitor.json and history.jsonl.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\dist\CCGuard"
#endif

[Setup]
AppId={{6F1D3C2A-8B4E-4F7A-9C55-2E8D41B7A0C3}
AppName=CCGuard
AppVersion={#AppVersion}
AppVerName=CCGuard {#AppVersion}
AppPublisher=CCGuard
AppPublisherURL=https://github.com/SumitaRinku/CCguard
AppSupportURL=https://github.com/SumitaRinku/CCguard/issues
AppUpdatesURL=https://github.com/SumitaRinku/CCguard/releases
DefaultDirName={localappdata}\Programs\CCGuard
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=CCGuard-Setup-{#AppVersion}
SetupIconFile=..\skills\claude-guardian\assets\monitor\icon-ok.ico
UninstallDisplayIcon={app}\CCGuard.exe
UninstallDisplayName=CCGuard
LicenseFile=..\LICENSE
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Pick the wizard language from the Windows UI language; ask only when neither matches.
ShowLanguageDialog=auto
; The panel holds this mutex (Local\CCGuard.Monitor.Instance): ask to close it before files change.
AppMutex=CCGuard.Monitor.Instance
CloseApplications=yes
VersionInfoVersion={#AppVersion}
VersionInfoProductName=CCGuard
VersionInfoDescription=CCGuard Setup

[Languages]
; languages\ChineseSimplified.isl: the user-contributed translation from the official Inno Setup
; repository (jrsoftware/issrc, Files/Languages/Unofficial, tag is-6_7_4, commit c2913c99),
; kept byte for byte with its translator credits; Inno Setup does not install it by default.
Name: "chinesesimplified"; MessagesFile: "languages\ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Same path and app id that monitor.py uses for notification identity (Start Menu\Programs\CCGuard.lnk).
Name: "{userprograms}\CCGuard"; Filename: "{app}\CCGuard.exe"; WorkingDir: "{app}"; AppUserModelID: "CCGuard.Monitor"
Name: "{userdesktop}\CCGuard"; Filename: "{app}\CCGuard.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\CCGuard.exe"; Description: "{cm:LaunchProgram,CCGuard}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Created by the panel's optional autostart switch.
Type: files; Name: "{userstartup}\CCGuard.lnk"
