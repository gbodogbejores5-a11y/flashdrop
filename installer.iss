; Installeur jrsdrop (Inno Setup). Compile avec : iscc /DAppVersion=3.0 installer.iss
#ifndef AppVersion
  #define AppVersion "3.0"
#endif

[Setup]
AppId={{7B3E5A1C-4F2D-4C8A-9E61-0A1B2C3D4E5F}
AppName=jrsdrop
AppVersion={#AppVersion}
AppPublisher=Africa Golden Digital
DefaultDirName={autopf}\jrsdrop
DefaultGroupName=jrsdrop
OutputDir=dist
OutputBaseFilename=jrsdrop-setup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\jrsdrop.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"

[Tasks]
Name: "desktopicon"; Description: "Créer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"

[Files]
Source: "dist\jrsdrop.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\jrsdrop"; Filename: "{app}\jrsdrop.exe"
Name: "{autodesktop}\jrsdrop"; Filename: "{app}\jrsdrop.exe"; Tasks: desktopicon

[Run]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""jrsdrop TCP"" dir=in action=allow protocol=TCP localport=50555 program=""{app}\jrsdrop.exe"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""jrsdrop UDP"" dir=in action=allow protocol=UDP localport=50556 program=""{app}\jrsdrop.exe"""; Flags: runhidden
Filename: "{app}\jrsdrop.exe"; Description: "Lancer jrsdrop maintenant"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""jrsdrop TCP"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""jrsdrop UDP"""; Flags: runhidden