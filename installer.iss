; Installeur JRSDrop (Inno Setup). Compile avec : iscc /DAppVersion=3.0 installer.iss
#ifndef AppVersion
  #define AppVersion "3.0"
#endif

[Setup]
AppId={{7B3E5A1C-4F2D-4C8A-9E61-0A1B2C3D4E5F}
AppName=JRSDrop
AppVersion={#AppVersion}
AppPublisher=Africa Golden Digital
DefaultDirName={autopf}\JRSDrop
DefaultGroupName=JRSDrop
OutputDir=dist
OutputBaseFilename=JRSDrop-Setup
SetupIconFile=assets\icon.ico
UninstallDisplayIcon={app}\JRSDrop.exe
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
Source: "dist\JRSDrop.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\JRSDrop"; Filename: "{app}\JRSDrop.exe"
Name: "{autodesktop}\JRSDrop"; Filename: "{app}\JRSDrop.exe"; Tasks: desktopicon

[Run]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""JRSDrop TCP"" dir=in action=allow protocol=TCP localport=50555 program=""{app}\JRSDrop.exe"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""JRSDrop UDP"" dir=in action=allow protocol=UDP localport=50556 program=""{app}\JRSDrop.exe"""; Flags: runhidden
Filename: "{app}\JRSDrop.exe"; Description: "Lancer JRSDrop maintenant"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""JRSDrop TCP"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""JRSDrop UDP"""; Flags: runhidden