; meshctx Desktop NSIS v3.115 — 10语言本地化
; MUI_LANGDLL 原生语言选择 → 安装程序启动即弹语言选择框
Unicode true
!include "MUI2.nsh"

Name "MeshCtx Desktop"
OutFile "dist\meshctx-setup.exe"
InstallDir "$PROGRAMFILES\MeshCtx"
RequestExecutionLevel admin

; 2026-08-25 004meshctx: 安装器品牌图标 (logo.ico 由新品牌 logo 生成)
!define MUI_ICON "logo.ico"
!define MUI_UNICON "logo.ico"

!define VERSION "3.125.0"
VIProductVersion "3.125.0.0"
VIAddVersionKey "FileVersion" "3.125.0"
VIAddVersionKey "ProductVersion" "3.125.0"
VIAddVersionKey "ProductName" "MeshCtx Desktop"
VIAddVersionKey "FileDescription" "MeshCtx Desktop Installer"

; ═══ 安装页面 ═══
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

; ═══ 10语言支持（必须在PAGE之后、onInit之前） ═══
!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "Japanese"
!insertmacro MUI_LANGUAGE "Korean"
!insertmacro MUI_LANGUAGE "German"
!insertmacro MUI_LANGUAGE "French"
!insertmacro MUI_LANGUAGE "Spanish"
!insertmacro MUI_LANGUAGE "Italian"
!insertmacro MUI_LANGUAGE "Arabic"
!insertmacro MUI_LANGUAGE "Hebrew"

; ═══ 语言选择对话框（必须在LANGUAGE之后） ═══
!define MUI_LANGDLL_ALLLANGUAGES
Function .onInit
  !insertmacro MUI_LANGDLL_DISPLAY
FunctionEnd

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
