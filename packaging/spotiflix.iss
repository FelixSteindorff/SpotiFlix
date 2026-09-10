; Installationsprogramm für SpotiFlix (Inno Setup 6).
;
; Bewusst ohne Administratorrechte: Die Installation landet im Benutzerprofil,
; legt einen Startmenü-Eintrag an und lässt sich normal deinstallieren. Die
; Version kommt über die Kommandozeile von build_release.py:
;
;   ISCC.exe /DMyAppVersion=1.1.0 packaging\spotiflix.iss

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#define MyAppName "SpotiFlix"
#define MyAppExe "SpotiFlix.exe"
#define MyAppPublisher "Felix Steindorff"
#define MyAppUrl "https://github.com/FelixSteindorff/SpotiFlix"

[Setup]
AppId={{8F3C9A21-4B7E-4E19-9C2A-5D1F6B8E7A34}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppUrl}
AppSupportURL={#MyAppUrl}/issues
AppUpdatesURL={#MyAppUrl}/releases
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename={#MyAppName}-{#MyAppVersion}-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName={#MyAppName} {#MyAppVersion}
UninstallDisplayIcon={app}\{#MyAppExe}

[Languages]
Name: "deutsch"; MessagesFile: "compiler:Languages\German.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Der komplette One-Dir-Build aus PyInstaller, inklusive librespot.exe,
; der NVDA-Controller-DLLs und der Übersetzungskataloge.
Source: "..\dist\{#MyAppName}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Die Einstellungen und Anmeldedaten liegen im Benutzerprofil und bleiben
; absichtlich erhalten – nur der Programmordner wird entfernt.
Type: filesandordirs; Name: "{app}\_internal"
