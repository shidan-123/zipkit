; ZipKit Windows 安装包（Inno Setup 6）
;
; 只能在 Windows 上编译：
;   ISCC.exe /DMyAppVersion=1.2.0 packaging\windows-installer.iss
;
; 注意：本文件里所有相对路径都以【脚本所在目录 packaging\】为基准，
; 不是仓库根目录。写成 ..\dist\ 才是根目录下的 dist。
;
; 设计取舍：
;   1. PrivilegesRequired=lowest —— 装到当前用户目录，不需要管理员权限。
;      机房、公司电脑常常没有管理员密码，这一步能少一半麻烦。
;   2. 不抢 .zip 文件关联 —— 用户装完直接替换掉系统解压工具，是最招人烦的行为。
;   3. 安装包只是一层壳：程序本身仍是免安装的，删掉安装目录也能直接跑。

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#define MyAppName "ZipKit"
#define MyAppPublisher "shidan-123"
#define MyAppURL "https://github.com/shidan-123/zipkit"
#define MyAppExeName "ZipKit.exe"

[Setup]
AppId={{171D9885-892A-45C0-8A3F-E890570793FE}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}/issues
AppUpdatesURL={#MyAppURL}/releases
DefaultDirName={localappdata}\Programs\ZipKit
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=..\dist
OutputBaseFilename=ZipKit-{#MyAppVersion}-windows-x64-setup
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=..\build\icon.ico

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional tasks:"

[Files]
Source: "..\dist\ZipKit.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\zipkit.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "使用说明.txt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\ZipKit"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall ZipKit"; Filename: "{uninstallexe}"
Name: "{autodesktop}\ZipKit"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch ZipKit"; Flags: nowait postinstall skipifsilent
