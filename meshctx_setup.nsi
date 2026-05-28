; meshctx Desktop NSIS Installer — 7语言版
Unicode true
!include "MUI2.nsh"

Name "MeshCtx Desktop"
OutFile "dist\meshctx-setup.exe"
InstallDir "$PROGRAMFILES\MeshCtx"
RequestExecutionLevel admin

!define VERSION "3.33.8"
VIProductVersion "3.33.4.0"
VIAddVersionKey "FileVersion" "3.33.4"
VIAddVersionKey "ProductName" "MeshCtx Desktop"
VIAddVersionKey "ProductVersion" "3.33.4"
VIAddVersionKey "FileDescription" "MeshCtx Desktop Installer"
VIAddVersionKey "LegalCopyright" "MIT License"

!define MUI_BUTTONTEXT_FINISH "Finish"

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
