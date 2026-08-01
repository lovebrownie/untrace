; Untrace Windows installer — compiled by ISCC from scripts/build.py
; Defines passed on the command line:
;   MyAppVersion, MyAppPublisher, MyAppCopyright,
;   SourceExe, RepoRoot, OutputDir, VcRedist, InnoSetupInstaller

#ifndef MyAppVersion
  #define MyAppVersion "0.1.0"
#endif
#ifndef MyAppPublisher
  #define MyAppPublisher "Untrace"
#endif
#ifndef MyAppCopyright
  #define MyAppCopyright "Copyright (C) 2026"
#endif
#ifndef SourceExe
  #define SourceExe "untrace.exe"
#endif
#ifndef RepoRoot
  #define RepoRoot ".."
#endif
#ifndef OutputDir
  #define OutputDir "dist"
#endif
#ifndef VcRedist
  #define VcRedist "VC_redist.x64.exe"
#endif
#ifndef InnoSetupInstaller
  #define InnoSetupInstaller "innosetup-6.7.3.exe"
#endif

#define MyAppName "Untrace"
#define MyAppExeName "untrace.exe"
#define VcRedistFile ExtractFileName(VcRedist)
#define InnoSetupFile ExtractFileName(InnoSetupInstaller)

[Setup]
AppId={{A7E8C3D1-9B2F-4E6A-8D1C-5F0B3A9E7C24}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
LicenseFile={#RepoRoot}\LICENSE
OutputDir={#OutputDir}
OutputBaseFilename=Untrace-v{#MyAppVersion}-Setup
SetupIconFile={#RepoRoot}\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesEnvironment=yes
MinVersion=10.0
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany={#MyAppPublisher}
VersionInfoDescription={#MyAppName} setup
VersionInfoCopyright={#MyAppCopyright}
VersionInfoProductName={#MyAppName}
VersionInfoProductVersion={#MyAppVersion}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "addpath"; Description: "Add Untrace to the system PATH"; GroupDescription: "Environment:"; Flags: checkedonce
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#SourceExe}"; DestDir: "{app}"; DestName: "{#MyAppExeName}"; Flags: ignoreversion
Source: "{#RepoRoot}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RepoRoot}\assets\icon.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#VcRedist}"; DestDir: "{tmp}"; Flags: dontcopy
Source: "{#InnoSetupInstaller}"; DestDir: "{tmp}"; Flags: dontcopy

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--gui"; Comment: "Untrace install manager"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Parameters: "--gui"; Tasks: desktopicon

[Registry]
Root: HKLM; Subkey: "SYSTEM\CurrentControlSet\Control\Session Manager\Environment"; \
    ValueType: expandsz; ValueName: "Path"; ValueData: "{olddata};{app}"; \
    Tasks: addpath; Check: NeedsAddPath(ExpandConstant('{app}'))

[Run]
Filename: "{app}\{#MyAppExeName}"; Parameters: "--gui"; Description: "Launch Untrace"; Flags: nowait postinstall skipifsilent shellexec

[Code]
procedure InitializeWizard;
begin
  WizardSelectTasks('addpath');
end;

function NeedsAddPath(Param: string): Boolean;
var
  OrigPath: string;
begin
  if not RegQueryStringValue(HKEY_LOCAL_MACHINE,
    'SYSTEM\CurrentControlSet\Control\Session Manager\Environment',
    'Path', OrigPath) then
  begin
    Result := True;
    exit;
  end;
  Result := Pos(';' + UpperCase(Param) + ';', ';' + UpperCase(OrigPath) + ';') = 0;
end;

procedure SetStatus(const Msg: string);
begin
  if WizardForm <> nil then
    WizardForm.StatusLabel.Caption := Msg;
end;

function VCRedistInstalled: Boolean;
var
  Installed: Cardinal;
begin
  Result :=
    RegQueryDWordValue(HKEY_LOCAL_MACHINE,
      'SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\X64',
      'Installed', Installed) and (Installed = 1);
end;

function InnoSetupInstalled: Boolean;
begin
  Result :=
    FileExists(ExpandConstant('{pf32}\Inno Setup 6\ISCC.exe')) or
    FileExists(ExpandConstant('{pf}\Inno Setup 6\ISCC.exe')) or
    FileExists(ExpandConstant('{localappdata}\Programs\Inno Setup 6\ISCC.exe'));
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  NeedsRestart := False;

  ExtractTemporaryFile('{#VcRedistFile}');
  ExtractTemporaryFile('{#InnoSetupFile}');

  if not VCRedistInstalled then
  begin
    SetStatus('Installing Visual C++ Redistributable...');
    if not Exec(
      ExpandConstant('{tmp}\{#VcRedistFile}'),
      '/install /quiet /norestart',
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode
    ) then
    begin
      Result := 'Failed to launch Visual C++ Redistributable.';
      exit;
    end;
    if (ResultCode <> 0) and (ResultCode <> 3010) then
    begin
      Result := 'Visual C++ Redistributable failed (exit ' + IntToStr(ResultCode) + ').';
      exit;
    end;
    if ResultCode = 3010 then
      NeedsRestart := True;
  end;

  if not InnoSetupInstalled then
  begin
    SetStatus('Installing Inno Setup 6...');
    if not Exec(
      ExpandConstant('{tmp}\{#InnoSetupFile}'),
      '/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-',
      '', SW_HIDE, ewWaitUntilTerminated, ResultCode
    ) then
    begin
      Result := 'Failed to launch Inno Setup installer.';
      exit;
    end;
    if ResultCode <> 0 then
    begin
      Result := 'Inno Setup installer failed (exit ' + IntToStr(ResultCode) + ').';
      exit;
    end;
  end;

  SetStatus('Installing Untrace...');
end;
