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

!define VERSION "1.3.2"
!define PUBLISHER "meshctx.com"

; ── 语言选择页面 (安装前) ──────────────────
Var SelectedLang
Page custom LangPage LangPageLeave
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

; ── 界面图标 ────────────────────────────────
!define MUI_ABORTWARNING
!define MUI_ICON "logo.ico"
!define MUI_UNICON "logo.ico"

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
