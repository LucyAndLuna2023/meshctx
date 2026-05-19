; meshctx Desktop — NSIS Unicode v2.25.0
; 7语言 + MUI_LANGDLL
; $\n for newlines in LangStrings (NOT $\\n)
; 构建: makensis meshctx_setup.nsi

Unicode true
!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"

Name "MeshCtx Desktop"
OutFile "dist\meshctx-setup.exe"
InstallDir "$PROGRAMFILES\MeshCtx"
RequestExecutionLevel admin
SetCompressor /SOLID lzma

!define VERSION "2.25.0"
!define PUBLISHER "meshctx.com"

!define MUI_ABORTWARNING
!define MUI_ICON "logo.ico"
!define MUI_UNICON "logo.ico"

; ── 7语言欢迎词 ──
LangString WELCOME_TITLE 1033 "MeshCtx Desktop v${VERSION}"
LangString WELCOME_TITLE 2052 "MeshCtx 桌面 v${VERSION}"
LangString WELCOME_TITLE 1041 "MeshCtx デスクトップ v${VERSION}"
LangString WELCOME_TITLE 1042 "MeshCtx 데스크탑 v${VERSION}"
LangString WELCOME_TITLE 1036 "MeshCtx Desktop v${VERSION}"
LangString WELCOME_TITLE 1031 "MeshCtx Desktop v${VERSION}"
LangString WELCOME_TITLE 1034 "MeshCtx Escritorio v${VERSION}"

LangString WELCOME_TEXT 1033 "The first self-evolving AI Agent for Windows.$\n$\nThis wizard will install MeshCtx on your computer.$\n$\nClick Install to begin."
LangString WELCOME_TEXT 2052 "世界首个自进化AI Agent系统，Windows原生客户端。$\n$\n本向导将在您的电脑上安装 MeshCtx。$\n$\n点击 安装 开始。"
LangString WELCOME_TEXT 1041 "世界初の自己進化AIエージェント、Windowsネイティブクライアント。$\n$\nこのウィザードは MeshCtx をインストールします。$\n$\nインストール をクリックして開始。"
LangString WELCOME_TEXT 1042 "세계 최초 자기진화 AI 에이전트, Windows 네이티브 클라이언트.$\n$\n이 마법사는 MeshCtx를 설치합니다.$\n$\n설치를 클릭하여 시작하세요."
LangString WELCOME_TEXT 1036 "Le premier agent IA auto-evolutif pour Windows.$\n$\nCet assistant installera MeshCtx sur votre ordinateur.$\n$\nCliquez sur Installer pour commencer."
LangString WELCOME_TEXT 1031 "Der erste selbstentwickelnde KI-Agent fur Windows.$\n$\nDieser Assistent installiert MeshCtx auf Ihrem Computer.$\n$\nKlicken Sie auf Installieren, um zu beginnen."
LangString WELCOME_TEXT 1034 "El primer agente IA autoevolutivo para Windows.$\n$\nEste asistente instalara MeshCtx en su equipo.$\n$\nHaga clic en Instalar para comenzar."

!define MUI_WELCOMEPAGE_TITLE "$(WELCOME_TITLE)"
!define MUI_WELCOMEPAGE_TEXT "$(WELCOME_TEXT)"

; ── 7语言目录页 ──
LangString DIR_TEXT 1033 "Choose install folder.$\n$\nSetup will install MeshCtx in the following folder.$\nTo install in a different folder, click Browse."
LangString DIR_TEXT 2052 "选择安装目录。$\n$\n安装程序将把 MeshCtx 安装到以下目录。$\n如需安装到其他目录，请点击浏览。"
LangString DIR_TEXT 1041 "インストール先を選択してください。$\n$\nMeshCtx を以下のフォルダにインストールします。$\n別のフォルダにインストールする場合は、参照をクリック。"
LangString DIR_TEXT 1042 "설치 폴더를 선택하세요.$\n$\nMeshCtx를 다음 폴더에 설치합니다.$\n다른 폴더에 설치하려면 찾아보기를 클릭하세요."
LangString DIR_TEXT 1036 "Choisissez le dossier d'installation.$\n$\nMeshCtx sera installe dans le dossier suivant.$\nPour un autre dossier, cliquez sur Parcourir."
LangString DIR_TEXT 1031 "Wahlen Sie den Installationsordner.$\n$\nMeshCtx wird im folgenden Ordner installiert.$\nFur einen anderen Ordner klicken Sie auf Durchsuchen."
LangString DIR_TEXT 1034 "Elija la carpeta de instalacion.$\n$\nMeshCtx se instalara en la siguiente carpeta.$\nPara otra carpeta, haga clic en Examinar."

!define MUI_DIRECTORYPAGE_TEXT_TOP "$(DIR_TEXT)"

; ── 页面顺序 ──
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

; ── 7语言注册 ──
!define MUI_LANGDLL_REGISTRY_ROOT "HKLM"
!define MUI_LANGDLL_REGISTRY_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx"
!define MUI_LANGDLL_REGISTRY_VALUENAME "Installer Language"
!define MUI_LANGDLL_ALLLANGUAGES
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "Japanese"
!insertmacro MUI_LANGUAGE "Korean"
!insertmacro MUI_LANGUAGE "German"
!insertmacro MUI_LANGUAGE "French"
!insertmacro MUI_LANGUAGE "Spanish"

Function .onInit
  !insertmacro MUI_LANGDLL_DISPLAY
FunctionEnd

; ── 安装(用户数据保留在 %USERPROFILE%\.meshctx) ──
Section "MeshCtx Desktop" SecMain
    SetOutPath "$INSTDIR"
    File "dist\meshctx-desktop.exe"
    Rename "$INSTDIR\meshctx-desktop.exe" "$INSTDIR\MeshCtx.exe"
    File "logo.ico"
    File "README.md"
    Rename "$INSTDIR\README.md" "$INSTDIR\README.txt"
    
    WriteUninstaller "$INSTDIR\uninstall.exe"
    
    CreateDirectory "$SMPROGRAMS\MeshCtx"
    CreateShortcut "$SMPROGRAMS\MeshCtx\MeshCtx.lnk" "$INSTDIR\MeshCtx.exe" "" "$INSTDIR\logo.ico"
    CreateShortcut "$SMPROGRAMS\MeshCtx\Uninstall.lnk" "$INSTDIR\uninstall.exe"
    
    CreateShortcut "$DESKTOP\MeshCtx.lnk" "$INSTDIR\MeshCtx.exe" "" "$INSTDIR\logo.ico"
    
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx" \
        "DisplayName" "MeshCtx Desktop"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx" \
        "UninstallString" "$INSTDIR\uninstall.exe"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx" \
        "DisplayIcon" "$INSTDIR\logo.ico"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx" \
        "Publisher" "${PUBLISHER}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx" \
        "DisplayVersion" "${VERSION}"
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx" \
        "NoModify" 1
    
    ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
    IntFmt $0 "0x%08X" $0
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx" \
        "EstimatedSize" "$0"
SectionEnd

; ── 卸载(只删程序,保留用户数据) ──
Section "Uninstall"
    Delete "$INSTDIR\MeshCtx.exe"
    Delete "$INSTDIR\logo.ico"
    Delete "$INSTDIR\README.txt"
    Delete "$INSTDIR\uninstall.exe"
    RMDir "$INSTDIR"
    
    Delete "$SMPROGRAMS\MeshCtx\MeshCtx.lnk"
    Delete "$SMPROGRAMS\MeshCtx\Uninstall.lnk"
    RMDir "$SMPROGRAMS\MeshCtx"
    
    Delete "$DESKTOP\MeshCtx.lnk"
    
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx"
SectionEnd
