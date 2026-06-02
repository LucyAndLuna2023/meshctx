; meshctx Desktop NSIS v3.115 — 7语言本地化
; MUI_LANGDLL 原生语言选择 → 页面创建前完成语言切换
Unicode true
!include "MUI2.nsh"

Name "MeshCtx Desktop"
OutFile "dist\meshctx-setup.exe"
InstallDir "$PROGRAMFILES\MeshCtx"
RequestExecutionLevel admin

!define VERSION "3.115.0"
VIProductVersion "3.115.0.0"
VIAddVersionKey "FileVersion" "3.115.0"
VIAddVersionKey "ProductVersion" "3.115.0"
VIAddVersionKey "ProductName" "MeshCtx Desktop"
VIAddVersionKey "FileDescription" "MeshCtx Desktop Installer"

; ═══ 语言选择 (onInit中，页面创建前) ═══
Function .onInit
  !insertmacro MUI_LANGDLL_DISPLAY
FunctionEnd

; ═══ 安装页面 ═══
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

; ═══ 7语言支持 (必须在所有PAGE之后) ═══
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "Japanese"
!insertmacro MUI_LANGUAGE "Korean"
!insertmacro MUI_LANGUAGE "German"
!insertmacro MUI_LANGUAGE "French"
!insertmacro MUI_LANGUAGE "Spanish"

; ═══ 静默安装跳过语言选择 ═══
Function .onInstSuccess
FunctionEnd

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
