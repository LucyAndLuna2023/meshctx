; meshctx Desktop NSIS v3.80 — 7语言本地化
; LangPageCreate→Leave设$LANGUAGE→MUI标准页面自动翻译
Unicode true
!include "MUI2.nsh"
!include "nsDialogs.nsh"

Name "MeshCtx Desktop"
OutFile "dist\meshctx-setup.exe"
InstallDir "$PROGRAMFILES\MeshCtx"
RequestExecutionLevel admin

!define VERSION "3.91.0"
VIProductVersion "3.83.0.0"
VIAddVersionKey "FileVersion" "3.83.0"
VIAddVersionKey "ProductVersion" "3.83.0"
VIAddVersionKey "ProductName" "MeshCtx Desktop"
VIAddVersionKey "FileDescription" "MeshCtx Desktop Installer"

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
FunctionEnd

Function LangPageLeave
  ${NSD_GetState} $RadioEn $0
  ${If} $0 == 1
    StrCpy $LANGUAGE 1033 ; English
    Return
  ${EndIf}
  ${NSD_GetState} $RadioZh $0
  ${If} $0 == 1
    StrCpy $LANGUAGE 2052 ; SimpChinese
    Return
  ${EndIf}
  ${NSD_GetState} $RadioJa $0
  ${If} $0 == 1
    StrCpy $LANGUAGE 1041 ; Japanese
    Return
  ${EndIf}
  ${NSD_GetState} $RadioKo $0
  ${If} $0 == 1
    StrCpy $LANGUAGE 1042 ; Korean
    Return
  ${EndIf}
  ${NSD_GetState} $RadioDe $0
  ${If} $0 == 1
    StrCpy $LANGUAGE 1031 ; German
    Return
  ${EndIf}
  ${NSD_GetState} $RadioFr $0
  ${If} $0 == 1
    StrCpy $LANGUAGE 1036 ; French
    Return
  ${EndIf}
  ${NSD_GetState} $RadioEs $0
  ${If} $0 == 1
    StrCpy $LANGUAGE 1034 ; Spanish
    Return
  ${EndIf}
FunctionEnd

Page custom LangPageCreate LangPageLeave
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "Japanese"
!insertmacro MUI_LANGUAGE "Korean"
!insertmacro MUI_LANGUAGE "German"
!insertmacro MUI_LANGUAGE "French"
!insertmacro MUI_LANGUAGE "Spanish"

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
