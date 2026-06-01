; meshctx Desktop NSIS v3.43 — 7语言完整本地化
; 🔴 MUI_PAGE必须在MUI_LANGUAGE之前（NSIS官方要求）
; 🔴 自定义radio运行时设置$LANGUAGE → 标准页面自动翻译
Unicode true
!include "MUI2.nsh"
!include "nsDialogs.nsh"

Name "MeshCtx Desktop"
OutFile "dist\meshctx-setup.exe"
InstallDir "$PROGRAMFILES\MeshCtx"
RequestExecutionLevel admin

!define VERSION "3.74.0"
VIProductVersion "3.47.0.0"
VIAddVersionKey "FileVersion" "3.47.0"
VIAddVersionKey "ProductVersion" "3.47.0"
VIAddVersionKey "ProductName" "MeshCtx Desktop"
VIAddVersionKey "FileDescription" "MeshCtx Desktop Installer"
VIAddVersionKey "LegalCopyright" "MIT License"

; ── 自定义语言选择页 ──
Var Dialog
Var RadioEn
Var RadioZh
Var RadioJa
Var RadioKo
Var RadioDe
Var RadioFr
Var RadioEs

Function LangPageCreate
  nsDialogs::Create 1018
  Pop $Dialog
  ${If} $Dialog == error
    Abort
  ${EndIf}
  
  ${NSD_CreateLabel} 0 0u 100% 12u "Select your language / 选择语言 / Sprache wählen:"
  Pop $0
  
  ${NSD_CreateRadioButton} 10u 20u 100% 12u "English"
  Pop $RadioEn
  ${NSD_Check} $RadioEn
  
  ${NSD_CreateRadioButton} 10u 35u 100% 12u "简体中文 (SimpChinese)"
  Pop $RadioZh
  
  ${NSD_CreateRadioButton} 10u 50u 100% 12u "日本語 (Japanese)"
  Pop $RadioJa
  
  ${NSD_CreateRadioButton} 10u 65u 100% 12u "한국어 (Korean)"
  Pop $RadioKo
  
  ${NSD_CreateRadioButton} 10u 80u 100% 12u "Deutsch (German)"
  Pop $RadioDe
  
  ${NSD_CreateRadioButton} 10u 95u 100% 12u "Français (French)"
  Pop $RadioFr
  
  ${NSD_CreateRadioButton} 10u 110u 100% 12u "Español (Spanish)"
  Pop $RadioEs
  
  nsDialogs::Show
FunctionEnd

Function LangPageLeave
  ${NSD_GetState} $RadioEn $0
  ${If} $0 == 1
    StrCpy $LANGUAGE 1033  ; English
    Goto lang_done
  ${EndIf}
  ${NSD_GetState} $RadioZh $0
  ${If} $0 == 1
    StrCpy $LANGUAGE 2052  ; SimpChinese
    Goto lang_done
  ${EndIf}
  ${NSD_GetState} $RadioJa $0
  ${If} $0 == 1
    StrCpy $LANGUAGE 1041  ; Japanese
    Goto lang_done
  ${EndIf}
  ${NSD_GetState} $RadioKo $0
  ${If} $0 == 1
    StrCpy $LANGUAGE 1042  ; Korean
    Goto lang_done
  ${EndIf}
  ${NSD_GetState} $RadioDe $0
  ${If} $0 == 1
    StrCpy $LANGUAGE 1031  ; German
    Goto lang_done
  ${EndIf}
  ${NSD_GetState} $RadioFr $0
  ${If} $0 == 1
    StrCpy $LANGUAGE 1036  ; French
    Goto lang_done
  ${EndIf}
  ${NSD_GetState} $RadioEs $0
  ${If} $0 == 1
    StrCpy $LANGUAGE 1034  ; Spanish
    Goto lang_done
  ${EndIf}
  lang_done:
FunctionEnd

; ── 页面顺序 ──
Page custom LangPageCreate LangPageLeave  ; 先语言选择
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

; 🔴 MUI_LANGUAGE必须在MUI_PAGE之后（编译时绑定翻译到标准页面）
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "Japanese"
!insertmacro MUI_LANGUAGE "Korean"
!insertmacro MUI_LANGUAGE "German"
!insertmacro MUI_LANGUAGE "French"
!insertmacro MUI_LANGUAGE "Spanish"

; ── 安装/卸载 ──
Section "Install"
    SetOutPath "$INSTDIR"
    File "dist\meshctx-desktop.exe"
    CreateShortCut "$DESKTOP\MeshCtx.lnk" "$INSTDIR\meshctx-desktop.exe"
    WriteUninstaller "$INSTDIR\uninstall.exe"
SectionEnd

Section "Uninstall"
    Delete "$INSTDIR\meshctx-desktop.exe"
    Delete "$INSTDIR\uninstall.exe"
    RMDir "$INSTDIR"
    Delete "$DESKTOP\MeshCtx.lnk"
SectionEnd
