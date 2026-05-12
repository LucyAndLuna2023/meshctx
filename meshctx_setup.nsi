; meshctx Desktop — NSIS 安装脚本
; 构建: makensis meshctx_setup.nsi
; 输出: meshctx-setup-v1.3.exe

!include "MUI2.nsh"
!include "FileFunc.nsh"

; ── 基本信息 ────────────────────────────────
Name "meshctx Desktop"
OutFile "dist\meshctx-setup.exe"
InstallDir "$PROGRAMFILES\meshctx"
RequestExecutionLevel admin
SetCompressor /SOLID lzma

!define VERSION "1.3.1"
!define PUBLISHER "meshctx.com"

; ── 界面设置 ────────────────────────────────
!define MUI_ABORTWARNING
!define MUI_ICON "logo.ico"
!define MUI_UNICON "logo.ico"

; 欢迎页
!define MUI_WELCOMEPAGE_TITLE "meshctx Desktop v${VERSION}"
!define MUI_WELCOMEPAGE_TEXT "This wizard will install meshctx Desktop on your computer.$\n$\nmeshctx is the world's first self-evolving AI agent platform.$\n$\nClick Next to continue."

; 许可页
!define MUI_LICENSEPAGE_TEXT_TOP "License Agreement"
!define MUI_LICENSEPAGE_TEXT_BOTTOM "If you accept the terms, click I Agree."

; 安装目录页
!define MUI_DIRECTORYPAGE_TEXT_TOP "Choose Install Location"
!define MUI_DIRECTORYPAGE_TEXT_DESTINATION "Install Folder"

; 完成页
!define MUI_FINISHPAGE_RUN "$INSTDIR\meshctx.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Launch meshctx Desktop"
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\README.txt"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "View README"

; ── 语言 ──────────────────────────────────
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "LICENSE"
!insertmacro MUI_PAGE_DIRECTORY
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

; ── 安装区段 ──────────────────────────────
Section "meshctx Desktop" SecMain
    SetOutPath "$INSTDIR"
    
    ; 主程序
    File "dist\meshctx-desktop.exe"
    Rename "$INSTDIR\meshctx-desktop.exe" "$INSTDIR\meshctx.exe"
    File "logo.ico"
    File "README.md"
    
    ; 重命名README
    Rename "$INSTDIR\README.md" "$INSTDIR\README.txt"
    
    ; 写入默认配置
    CreateDirectory "$INSTDIR\config"
    FileOpen $0 "$INSTDIR\config\default.yaml" w
    FileWrite $0 "# meshctx 默认配置$\n"
    FileWrite $0 "# 首次运行后请通过 http://localhost:3000/ui/setup 配置 API Key$\n"
    FileWrite $0 "kernel:$\n"
    FileWrite $0 "  worker_count: 4$\n"
    FileWrite $0 "models:$\n"
    FileWrite $0 "  default: deepseek:chat$\n"
    FileWrite $0 "  entries: {}$\n"
    FileClose $0
    
    ; 开始菜单快捷方式
    CreateDirectory "$SMPROGRAMS\meshctx"
    CreateShortcut "$SMPROGRAMS\meshctx\meshctx Desktop.lnk" "$INSTDIR\meshctx.exe" "" "$INSTDIR\logo.ico"
    CreateShortcut "$SMPROGRAMS\meshctx\Uninstall.lnk" "$INSTDIR\uninstall.exe"
    
    ; 桌面快捷方式
    CreateShortcut "$DESKTOP\meshctx.lnk" "$INSTDIR\meshctx.exe" "" "$INSTDIR\logo.ico"
    
    ; 卸载程序
    WriteUninstaller "$INSTDIR\uninstall.exe"
    
    ; 注册表（添加/删除程序）
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\meshctx" \
        "DisplayName" "meshctx Desktop"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\meshctx" \
        "UninstallString" "$INSTDIR\uninstall.exe"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\meshctx" \
        "DisplayIcon" "$INSTDIR\logo.ico"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\meshctx" \
        "Publisher" "${PUBLISHER}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\meshctx" \
        "DisplayVersion" "${VERSION}"
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\meshctx" \
        "NoModify" 1
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\meshctx" \
        "NoRepair" 1
    
    ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
    IntFmt $0 "0x%08X" $0
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\meshctx" \
        "EstimatedSize" "$0"
SectionEnd

; ── 卸载区段 ──────────────────────────────
Section "Uninstall"
    Delete "$INSTDIR\meshctx.exe"
    Delete "$INSTDIR\logo.ico"
    Delete "$INSTDIR\README.txt"
    Delete "$INSTDIR\uninstall.exe"
    RMDir /r "$INSTDIR\config"
    RMDir "$INSTDIR"
    
    Delete "$SMPROGRAMS\meshctx\meshctx Desktop.lnk"
    Delete "$SMPROGRAMS\meshctx\Uninstall.lnk"
    RMDir "$SMPROGRAMS\meshctx"
    
    Delete "$DESKTOP\meshctx.lnk"
    
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\meshctx"
SectionEnd
