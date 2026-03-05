#define MyAppName "DnD Note Generator"
#define MyAppVersion "1.0"
#define MyAppExeName "DnD Notes.exe"

[Setup]
AppId={{8F3A2C1D-4B5E-4F6A-9D2E-1C3B5A7E9F0D}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=DnD Notes
DefaultDirName={localappdata}\DnD Notes
DefaultGroupName=DnD Notes
DisableProgramGroupPage=yes
OutputDir=.
OutputBaseFilename=DnDNotesSetup
SetupIconFile=icon.ico
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest
UninstallDisplayName={#MyAppName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"

[Files]
Source: "DnD Notes.exe";     DestDir: "{app}"; Flags: ignoreversion
Source: "app.py";            DestDir: "{app}"; Flags: ignoreversion
Source: "generate_notes.py"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}";  Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch DnD Note Generator now"; Flags: nowait postinstall skipifsilent

[Code]
function IsPythonInstalled(): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec(ExpandConstant('{cmd}'), '/C python --version', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := Result and (ResultCode = 0);
end;

function InitializeSetup(): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  if not IsPythonInstalled() then
  begin
    if MsgBox(
      'Python is not installed on this PC.' + #13#10 + #13#10 +
      'DnD Note Generator needs Python to transcribe audio and write notes.' + #13#10 + #13#10 +
      'Click OK to open the Python download page, then run this installer again.' + #13#10 +
      'Important: during install, tick the box that says "Add Python to PATH".',
      mbConfirmation, MB_OKCANCEL) = IDOK then
    begin
      ShellExec('open', 'https://www.python.org/downloads/', '', '', SW_SHOW, ewNoWait, ResultCode);
    end;
    Result := False;
  end;
end;
