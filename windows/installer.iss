; Inno Setup script for Multi-Out.
; Produces Output\Multi-Out-Setup.exe — a per-user installer that needs no
; admin rights, so it never triggers a UAC prompt.

#define AppName    "Multi-Out"
#define AppVersion "1.0.0"
#define AppExe     "Multi-Out.exe"

[Setup]
AppId={{8F3B1C24-6A5E-4D7B-9E12-4C0A7B2D5E91}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Tetfulo Nkambule
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=Multi-Out-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
; Per-user install: no admin rights, no UAC prompt.
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExe}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "autoswitch"; Description: "Switch to Bluetooth automatically when a device connects"; GroupDescription: "Startup"
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts"; Flags: unchecked

[Files]
Source: "dist\Multi-Out.exe";          DestDir: "{app}"; Flags: ignoreversion
Source: "dist\Multi-Out-Selftest.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md";                   DestDir: "{app}"; Flags: ignoreversion isreadme

[Icons]
Name: "{group}\{#AppName}";              Filename: "{app}\{#AppExe}"
Name: "{group}\{#AppName} self-test";    Filename: "{app}\Multi-Out-Selftest.exe"; Parameters: "--selftest"
Name: "{group}\Uninstall {#AppName}";    Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}";        Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
; Register the background auto-switch task, running as the installing user.
Filename: "schtasks.exe"; \
  Parameters: "/Create /F /SC ONLOGON /TN ""Multi-Out auto-switch"" /TR ""'{app}\{#AppExe}' --daemon"""; \
  Flags: runhidden; Tasks: autoswitch
Filename: "schtasks.exe"; \
  Parameters: "/Run /TN ""Multi-Out auto-switch"""; \
  Flags: runhidden; Tasks: autoswitch
Filename: "{app}\{#AppExe}"; Description: "Open {#AppName} now"; \
  Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "schtasks.exe"; Parameters: "/Delete /F /TN ""Multi-Out auto-switch"""; \
  Flags: runhidden; RunOnceId: "DelAutoSwitchTask"

[UninstallDelete]
Type: filesandordirs; Name: "{localappdata}\multiout"
