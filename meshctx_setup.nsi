; meshctx Desktop — NSIS 安装脚本 (Unicode)
; 构建: makensis meshctx_setup.nsi
; 输出: meshctx-setup.exe

Unicode true
!include "MUI2.nsh"
!include "FileFunc.nsh"

; ── 基本信息 ────────────────────────────────
Name "meshctx Desktop"
OutFile "dist\meshctx-setup.exe"
InstallDir "$PROGRAMFILES\meshctx"
RequestExecutionLevel admin
SetCompressor /SOLID lzma

!define VERSION "1.3.2"
!define PUBLISHER "meshctx.com"

; ── LangStrings (多语言自定义文本) ──────────
LangString WELCOME_TITLE ${LANG_ENGLISH} "meshctx Desktop v${VERSION}"
LangString WELCOME_TEXT ${LANG_ENGLISH} "This wizard will install meshctx Desktop on your computer.$\n$\nmeshctx is the world's first self-evolving AI agent platform.$\n$\nClick Next to continue."
LangString WELCOME_TITLE ${LANG_SIMPCHINESE} "meshctx Desktop v${VERSION}"
LangString WELCOME_TEXT ${LANG_SIMPCHINESE} "本向导将安装 meshctx Desktop 到您的计算机。$\n$\nmeshctx 是全球首个自进化 AI Agent 平台。$\n$\n点击下一步继续。"
LangString WELCOME_TITLE ${LANG_JAPANESE} "meshctx Desktop v${VERSION}"
LangString WELCOME_TEXT ${LANG_JAPANESE} "このウィザードは meshctx Desktop をコンピュータにインストールします。$\n$\nmeshctx は世界初の自己進化型AIエージェントプラットフォームです。$\n$\n「次へ」をクリックして続行。"
LangString WELCOME_TITLE ${LANG_KOREAN} "meshctx Desktop v${VERSION}"
LangString WELCOME_TEXT ${LANG_KOREAN} "이 마법사는 meshctx Desktop을 컴퓨터에 설치합니다.$\n$\nmeshctx는 세계 최초의 자기 진화형 AI 에이전트 플랫폼입니다.$\n$\n다음을 클릭하여 계속합니다."
LangString WELCOME_TITLE ${LANG_GERMAN} "meshctx Desktop v${VERSION}"
LangString WELCOME_TEXT ${LANG_GERMAN} "Dieser Assistent installiert meshctx Desktop auf Ihrem Computer.$\n$\nmeshctx ist die weltweit erste selbstlernende Agenten-Plattform.$\n$\nKlicken Sie auf Weiter."
LangString WELCOME_TITLE ${LANG_FRENCH} "meshctx Desktop v${VERSION}"
LangString WELCOME_TEXT ${LANG_FRENCH} "Cet assistant va installer meshctx Desktop sur votre ordinateur.$\n$\nmeshctx est la premiere plateforme d'agents auto-evolutive.$\n$\nCliquez sur Suivant."
LangString WELCOME_TITLE ${LANG_SPANISH} "meshctx Desktop v${VERSION}"
LangString WELCOME_TEXT ${LANG_SPANISH} "Este asistente instalara meshctx Desktop en su equipo.$\n$\nmeshctx es la primera plataforma de agentes auto-evolutiva.$\n$\nHaga clic en Siguiente."

LangString LAUNCH_TEXT ${LANG_ENGLISH} "Launch meshctx Desktop"
LangString LAUNCH_TEXT ${LANG_SIMPCHINESE} "启动 meshctx Desktop"
LangString LAUNCH_TEXT ${LANG_JAPANESE} "meshctx Desktop を起動"
LangString LAUNCH_TEXT ${LANG_KOREAN} "meshctx Desktop 실행"
LangString LAUNCH_TEXT ${LANG_GERMAN} "meshctx Desktop starten"
LangString LAUNCH_TEXT ${LANG_FRENCH} "Lancer meshctx Desktop"
LangString LAUNCH_TEXT ${LANG_SPANISH} "Iniciar meshctx Desktop"

LangString README_TEXT ${LANG_ENGLISH} "View README"
LangString README_TEXT ${LANG_SIMPCHINESE} "查看 README"
LangString README_TEXT ${LANG_JAPANESE} "README を表示"
LangString README_TEXT ${LANG_KOREAN} "README 보기"
LangString README_TEXT ${LANG_GERMAN} "README anzeigen"
LangString README_TEXT ${LANG_FRENCH} "Voir README"
LangString README_TEXT ${LANG_SPANISH} "Ver README"

LangString STARTMENU_FOLDER ${LANG_ENGLISH} "meshctx"
LangString STARTMENU_FOLDER ${LANG_SIMPCHINESE} "meshctx"
LangString STARTMENU_FOLDER ${LANG_JAPANESE} "meshctx"
LangString STARTMENU_FOLDER ${LANG_KOREAN} "meshctx"
LangString STARTMENU_FOLDER ${LANG_GERMAN} "meshctx"
LangString STARTMENU_FOLDER ${LANG_FRENCH} "meshctx"
LangString STARTMENU_FOLDER ${LANG_SPANISH} "meshctx"

LangString LICENSE_TOP ${LANG_ENGLISH} "License Agreement"
LangString LICENSE_BOTTOM ${LANG_ENGLISH} "If you accept the terms, click I Agree."
LangString LICENSE_TOP ${LANG_SIMPCHINESE} "许可协议"
LangString LICENSE_BOTTOM ${LANG_SIMPCHINESE} "如果接受条款，请点击我同意。"
LangString LICENSE_TOP ${LANG_JAPANESE} "ライセンス契約"
LangString LICENSE_BOTTOM ${LANG_JAPANESE} "同意する場合は「同意する」をクリック。"
LangString LICENSE_TOP ${LANG_KOREAN} "라이선스 계약"
LangString LICENSE_BOTTOM ${LANG_KOREAN} "동의하시면 '동의함'을 클릭하세요."
LangString LICENSE_TOP ${LANG_GERMAN} "Lizenzvereinbarung"
LangString LICENSE_BOTTOM ${LANG_GERMAN} "Wenn Sie zustimmen, klicken Sie auf Ich stimme zu."
LangString LICENSE_TOP ${LANG_FRENCH} "Contrat de licence"
LangString LICENSE_BOTTOM ${LANG_FRENCH} "Si vous acceptez, cliquez sur J'accepte."
LangString LICENSE_TOP ${LANG_SPANISH} "Acuerdo de Licencia"
LangString LICENSE_BOTTOM ${LANG_SPANISH} "Si acepta los terminos, haga clic en Acepto."

LangString DIR_TOP ${LANG_ENGLISH} "Choose Install Location"
LangString DIR_DEST ${LANG_ENGLISH} "Install Folder"
LangString DIR_TOP ${LANG_SIMPCHINESE} "选择安装位置"
LangString DIR_DEST ${LANG_SIMPCHINESE} "安装目录"
LangString DIR_TOP ${LANG_JAPANESE} "インストール先の選択"
LangString DIR_DEST ${LANG_JAPANESE} "インストールフォルダ"
LangString DIR_TOP ${LANG_KOREAN} "설치 위치 선택"
LangString DIR_DEST ${LANG_KOREAN} "설치 폴더"
LangString DIR_TOP ${LANG_GERMAN} "Installationsort wahlen"
LangString DIR_DEST ${LANG_GERMAN} "Installationsordner"
LangString DIR_TOP ${LANG_FRENCH} "Choisir l'emplacement"
LangString DIR_DEST ${LANG_FRENCH} "Dossier d'installation"
LangString DIR_TOP ${LANG_SPANISH} "Elegir ubicacion"
LangString DIR_DEST ${LANG_SPANISH} "Carpeta de instalacion"

; ── 界面设置 ────────────────────────────────
!define MUI_ABORTWARNING
!define MUI_ICON "logo.ico"
!define MUI_UNICON "logo.ico"

!define MUI_WELCOMEPAGE_TITLE "$(WELCOME_TITLE)"
!define MUI_WELCOMEPAGE_TEXT "$(WELCOME_TEXT)"
!define MUI_LICENSEPAGE_TEXT_TOP "$(LICENSE_TOP)"
!define MUI_LICENSEPAGE_TEXT_BOTTOM "$(LICENSE_BOTTOM)"
!define MUI_DIRECTORYPAGE_TEXT_TOP "$(DIR_TOP)"
!define MUI_DIRECTORYPAGE_TEXT_DESTINATION "$(DIR_DEST)"
!define MUI_FINISHPAGE_RUN "$INSTDIR\meshctx.exe"
!define MUI_FINISHPAGE_RUN_TEXT "$(LAUNCH_TEXT)"
!define MUI_FINISHPAGE_SHOWREADME "$INSTDIR\README.txt"
!define MUI_FINISHPAGE_SHOWREADME_TEXT "$(README_TEXT)"

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
!insertmacro MUI_LANGUAGE "Spanish"

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
