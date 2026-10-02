#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{B6F1E0A4-3C52-4D8B-9A7E-5E2D1C4F8A93}
AppName=Little Guy
AppVersion={#AppVersion}
AppPublisher=Ridit
DefaultDirName={autopf}\Little Guy
DefaultGroupName=Little Guy
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=LittleGuy-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\LittleGuy.exe

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked
Name: "startup"; Description: "Start Little Guy when I sign in"; GroupDescription: "Startup:"

[Files]
Source: "..\dist\LittleGuy.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Little Guy"; Filename: "{app}\LittleGuy.exe"
Name: "{group}\Uninstall Little Guy"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Little Guy"; Filename: "{app}\LittleGuy.exe"; Tasks: desktopicon
Name: "{userstartup}\Little Guy"; Filename: "{app}\LittleGuy.exe"; Tasks: startup

[Run]
Filename: "{app}\LittleGuy.exe"; Description: "Launch Little Guy"; Flags: nowait postinstall skipifsilent
