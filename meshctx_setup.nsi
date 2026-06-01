; meshctx Desktop NSIS v3.80 — 7语言本地化
; .onInit语言选择→设$LANGUAGE→MUI_PAGE用标准翻译
Unicode true
!include "MUI2.nsh"
!include "nsDialogs.nsh"

Name "MeshCtx Desktop"
OutFile "dist\meshctx-setup.exe"
InstallDir "$PROGRAMFILES\MeshCtx"
RequestExecutionLevel admin

!define VERSION "3.80.0"
VIProductVersion "3.80.0.0"
VIAddVersionKey "FileVersion" "3.80.0"
VIAddVersionKey "ProductVersion" "3.80.0"
VIAddVersionKey "ProductName" "MeshCtx Desktop"
VIAddVersionKey "FileDescription" "MeshCtx Desktop Installer"

; ── 变量 ──
Var Dialog
Var RadioEn
Var RadioZh
Var RadioJa
Var RadioKo
Var RadioDe
Var RadioFr
Var RadioEs

; ── .onInit: 在所有页面前弹出语言选择 ──
Function .onInit
  nsDialogs::Create 1018
  Pop $Dialog
  ${If} $Dialog == error
    Abort
  ${EndIf}
  
  ${NSD_CreateLabel} 0 0u 100% 12u "Select your language / 选择语言 / Sprache wahlen:"
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
  
  ${NSD_CreateRadioButton} 10u 95u 100% 12u "Francais (French)"
  Pop $RadioFr
  
  ${NSD_CreateRadioButton} 10u 110u 100% 12u "Espanol (Spanish)"
  Pop $RadioEs
  
  nsDialogs::Show
  
  ${NSD_GetState} $RadioEn $0
  ${If} $0 == 1
    StrCpy $LANGUAGE 1033
    Goto init_done
  ${EndIf}
  ${NSD_GetState} $RadioZh $0
  ${If} $0 == 1
    StrCpy $LANGUAGE 2052
    Goto init_done
  ${EndIf}
  ${NSD_GetState} $RadioJa $0
  ${If} $0 == 1
    StrCpy $LANGUAGE 1041
    Goto init_done
  ${EndIf}
  ${NSD_GetState} $RadioKo $0
  ${If} $0 == 1
    StrCpy $LANGUAGE 1042
    Goto init_done
  ${EndIf}
  ${NSD_GetState} $RadioDe $0
  ${If} $0 == 1
    StrCpy $LANGUAGE 1031
    Goto init_done
  ${EndIf}
  ${NSD_GetState} $RadioFr $0
  ${If} $0 == 1
    StrCpy $LANGUAGE 1036
    Goto init_done
  ${EndIf}
  ${NSD_GetState} $RadioEs $0
  ${If} $0 == 1
    StrCpy $LANGUAGE 1034
    Goto init_done
  ${EndIf}
  init_done:
FunctionEnd

; ── 标准页面 ──
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

; ── 7语言定义(NSIS要求PAGE之后) ──
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
