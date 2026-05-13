; meshctx Desktop — NSIS Unicode 安装脚本
; 7语言 + 语言选择页 + 路径选择
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

!define VERSION "1.5.24"
!define PUBLISHER "meshctx.com"

; ── 界面图标（必须在所有MUI_*之前） ─────────
!define MUI_ABORTWARNING
!define MUI_ICON "logo.ico"
!define MUI_UNICON "logo.ico"

; ── 7语言欢迎词 (LangString) ────────────────
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

; ── 语言选择页面 (安装前) ──────────────────
Var SelectedLang
Page custom LangPage LangPageLeave
!insertmacro MUI_PAGE_WELCOME
PageEx directory
  DirText "Choose install folder.$\n$\nSetup will install MeshCtx in the following folder."
PageExEnd
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "Japanese"
!insertmacro MUI_LANGUAGE "Korean"
!insertmacro MUI_LANGUAGE "German"
!insertmacro MUI_LANGUAGE "French"
!insertmacro MUI_LANGUAGE "Spanish"

; ── 语言选择页控件 ─────────────────────────
Function LangPage
  !insertmacro MUI_HEADER_TEXT "Select Language" "Please select your preferred language."
  nsDialogs::Create 1018
  Pop $0
  
  ${NSD_CreateLabel} 0 20u 100% 12u "Language / 语言 / Sprache / Langue / Idioma:"
  Pop $0
  
  ${NSD_CreateDropList} 0 40u 50% 120u ""
  Pop $0
  ${NSD_CB_AddString} $0 "English"
  ${NSD_CB_AddString} $0 "中文 (简体)"
  ${NSD_CB_AddString} $0 "日本語"
  ${NSD_CB_AddString} $0 "한국어"
  ${NSD_CB_AddString} $0 "Deutsch"
  ${NSD_CB_AddString} $0 "Français"
  ${NSD_CB_AddString} $0 "Español"
  ${NSD_CB_SelectString} $0 "English"
  
  nsDialogs::Show
FunctionEnd

Function LangPageLeave
  Pop $0
  ${NSD_GetText} $0 $SelectedLang
  ${If} $SelectedLang == "English"
    StrCpy $LANGUAGE ${LANG_ENGLISH}
  ${ElseIf} $SelectedLang == "中文 (简体)"
    StrCpy $LANGUAGE ${LANG_SIMPCHINESE}
  ${ElseIf} $SelectedLang == "日本語"
    StrCpy $LANGUAGE ${LANG_JAPANESE}
  ${ElseIf} $SelectedLang == "한국어"
    StrCpy $LANGUAGE ${LANG_KOREAN}
  ${ElseIf} $SelectedLang == "Deutsch"
    StrCpy $LANGUAGE ${LANG_GERMAN}
  ${ElseIf} $SelectedLang == "Français"
    StrCpy $LANGUAGE ${LANG_FRENCH}
  ${ElseIf} $SelectedLang == "Español"
    StrCpy $LANGUAGE ${LANG_SPANISH}
  ${EndIf}
FunctionEnd

; ── 欢迎标题(根据语言) ──────────────────────
Function .onInit
  ; 默认英语
  StrCpy $LANGUAGE ${LANG_ENGLISH}
FunctionEnd

; ── 安装区段 ──────────────────────────────
Section "MeshCtx Desktop" SecMain
    SetOutPath "$INSTDIR"
    
    ; 主程序
    File "dist\meshctx-desktop.exe"
    Rename "$INSTDIR\meshctx-desktop.exe" "$INSTDIR\MeshCtx.exe"
    File "logo.ico"
    File "README.md"
    Rename "$INSTDIR\README.md" "$INSTDIR\README.txt"
    
    ; 卸载程序
    WriteUninstaller "$INSTDIR\uninstall.exe"
    
    ; 开始菜单
    CreateDirectory "$SMPROGRAMS\MeshCtx"
    CreateShortcut "$SMPROGRAMS\MeshCtx\MeshCtx.lnk" "$INSTDIR\MeshCtx.exe" "" "$INSTDIR\logo.ico"
    CreateShortcut "$SMPROGRAMS\MeshCtx\Uninstall.lnk" "$INSTDIR\uninstall.exe"
    
    ; 桌面快捷方式
    CreateShortcut "$DESKTOP\MeshCtx.lnk" "$INSTDIR\MeshCtx.exe" "" "$INSTDIR\logo.ico"
    
    ; 注册表
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
