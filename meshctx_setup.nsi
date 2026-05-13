; meshctx Desktop — NSIS Unicode 安装脚本 v1.5.26
; 7语言 + MUI_LANGDLL(原生语言选择,解决乱码)
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

!define VERSION "1.5.26"
!define PUBLISHER "meshctx.com"

; ── 界面图标 ───────────────────────────────
!define MUI_ABORTWARNING
!define MUI_ICON "logo.ico"
!define MUI_UNICON "logo.ico"

; ── 7语言欢迎词 (LangString) ──────────────
LangString WELCOME_TITLE ${LANG_ENGLISH} "MeshCtx Desktop v${VERSION}"
LangString WELCOME_TITLE ${LANG_SIMPCHINESE} "MeshCtx 桌面 v${VERSION}"
LangString WELCOME_TITLE ${LANG_JAPANESE} "MeshCtx デスクトップ v${VERSION}"
LangString WELCOME_TITLE ${LANG_KOREAN} "MeshCtx 데스크탑 v${VERSION}"
LangString WELCOME_TITLE ${LANG_FRENCH} "MeshCtx Desktop v${VERSION}"
LangString WELCOME_TITLE ${LANG_GERMAN} "MeshCtx Desktop v${VERSION}"
LangString WELCOME_TITLE ${LANG_SPANISH} "MeshCtx Escritorio v${VERSION}"

LangString WELCOME_TEXT ${LANG_ENGLISH} "The first self-evolving AI Agent for Windows.$\n$\nThis wizard will install MeshCtx on your computer.$\n$\nClick Install to begin."
LangString WELCOME_TEXT ${LANG_SIMPCHINESE} "世界首个自进化AI Agent系统，Windows原生客户端。$\n$\n本向导将在您的电脑上安装 MeshCtx。$\n$\n点击 安装 开始。"
LangString WELCOME_TEXT ${LANG_JAPANESE} "世界初の自己進化AIエージェント、Windowsネイティブクライアント。$\n$\nこのウィザードは MeshCtx をインストールします。$\n$\nインストール をクリックして開始。"
LangString WELCOME_TEXT ${LANG_KOREAN} "세계 최초 자기진화 AI 에이전트, Windows 네이티브 클라이언트.$\n$\n이 마법사는 MeshCtx를 설치합니다.$\n$\n설치를 클릭하여 시작하세요."
LangString WELCOME_TEXT ${LANG_FRENCH} "Le premier agent IA auto-évolutif pour Windows.$\n$\nCet assistant installera MeshCtx sur votre ordinateur.$\n$\nCliquez sur Installer pour commencer."
LangString WELCOME_TEXT ${LANG_GERMAN} "Der erste selbstentwickelnde KI-Agent für Windows.$\n$\nDieser Assistent installiert MeshCtx auf Ihrem Computer.$\n$\nKlicken Sie auf Installieren, um zu beginnen."
LangString WELCOME_TEXT ${LANG_SPANISH} "El primer agente IA autoevolutivo para Windows.$\n$\nEste asistente instalará MeshCtx en su equipo.$\n$\nHaga clic en Instalar para comenzar."

!define MUI_WELCOMEPAGE_TITLE "$(WELCOME_TITLE)"
!define MUI_WELCOMEPAGE_TEXT "$(WELCOME_TEXT)"

; ── 页面顺序(语言选择由MUI_LANGDLL处理) ──
!insertmacro MUI_PAGE_WELCOME
PageEx directory
  DirText "Choose install folder.$\n$\nSetup will install MeshCtx in the following folder."
PageExEnd
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

; ── 7语言注册 ─────────────────────────────
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

; ── 安装前显示语言选择对话框 ──────────────
Function .onInit
  !insertmacro MUI_LANGDLL_DISPLAY
FunctionEnd

; ── 安装区段 ──────────────────────────────
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

; ── 卸载 ──────────────────────────────────
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
