; meshctx Desktop — NSIS Unicode v3.33.0
; 7语言自定义选择页（不依赖LangDLL插件）
; 构建: makensis meshctx_setup.nsi

Unicode true
!include "MUI2.nsh"
!include "FileFunc.nsh"
!include "LogicLib.nsh"

Name "MeshCtx Desktop"
!include "nsDialogs.nsh"
OutFile "dist\meshctx-setup.exe"
InstallDir "$PROGRAMFILES\MeshCtx"
RequestExecutionLevel admin
SetCompressor /SOLID lzma

!define VERSION "3.33.4"
!define PUBLISHER "meshctx.com"

!define MUI_ABORTWARNING
!define MUI_ICON "logo.ico"
!define MUI_UNICON "logo.ico"

; ── 安装欢迎 ──
LangString WELCOME_TITLE 1033 "MeshCtx Desktop v${VERSION}"
LangString WELCOME_TITLE 2052 "MeshCtx 桌面 v${VERSION}"
LangString WELCOME_TITLE 1041 "MeshCtx デスクトップ v${VERSION}"
LangString WELCOME_TITLE 1042 "MeshCtx 데스크탑 v${VERSION}"
LangString WELCOME_TITLE 1036 "MeshCtx Desktop v${VERSION}"
LangString WELCOME_TITLE 1031 "MeshCtx Desktop v${VERSION}"
LangString WELCOME_TITLE 1034 "MeshCtx Escritorio v${VERSION}"

; ── 目录选择 ──
LangString DIR_TEXT 1033 "Select installation folder"
LangString DIR_TEXT 2052 "选择安装目录"
LangString DIR_TEXT 1041 "インストール先を選択"
LangString DIR_TEXT 1042 "설치 폴더 선택"
LangString DIR_TEXT 1036 "Choisir le dossier"
LangString DIR_TEXT 1031 "Installationsordner wahlen"
LangString DIR_TEXT 1034 "Seleccionar carpeta"

; ── 正在安装 ──
LangString INSTALLING 1033 "Installing MeshCtx..."
LangString INSTALLING 2052 "正在安装 MeshCtx..."
LangString INSTALLING 1041 "MeshCtxをインストール中..."
LangString INSTALLING 1042 "MeshCtx 설치 중..."
LangString INSTALLING 1036 "Installation de MeshCtx..."
LangString INSTALLING 1031 "MeshCtx wird installiert..."
LangString INSTALLING 1034 "Instalando MeshCtx..."

; ── 安装完成 ──
LangString FINISH_TITLE 1033 "Installation Complete"
LangString FINISH_TITLE 2052 "安装完成"
LangString FINISH_TITLE 1041 "インストール完了"
LangString FINISH_TITLE 1042 "설치 완료"
LangString FINISH_TITLE 1036 "Installation terminee"
LangString FINISH_TITLE 1031 "Installation abgeschlossen"
LangString FINISH_TITLE 1034 "Instalacion completada"

LangString FINISH_TEXT 1033 "MeshCtx has been installed.$\n$\nStart from Start Menu or Desktop shortcut."
LangString FINISH_TEXT 2052 "MeshCtx 安装完成。$\n$\n从开始菜单或桌面快捷方式启动。"
LangString FINISH_TEXT 1041 "MeshCtx のインストールが完了しました。$\n$\nスタートメニューまたはデスクトップから起動。"
LangString FINISH_TEXT 1042 "MeshCtx 설치가 완료되었습니다.$\n$\n시작 메뉴 또는 바탕화면에서 실행하세요."
LangString FINISH_TEXT 1036 "MeshCtx a ete installe.$\n$\nLancez depuis le menu Demarrer ou le bureau."
LangString FINISH_TEXT 1031 "MeshCtx wurde installiert.$\n$\nStarten Sie uber das Startmenu oder die Desktop-Verknupfung."
LangString FINISH_TEXT 1034 "MeshCtx se ha instalado.$\n$\nInicie desde el menu Inicio o el escritorio."

; ── 完成按钮 ──
LangString FINISH_BUTTON 1033 "&Finish"
LangString FINISH_BUTTON 2052 "完成(&F)"
LangString FINISH_BUTTON 1041 "完了(&F)"
LangString FINISH_BUTTON 1042 "완료(&F)"
LangString FINISH_BUTTON 1036 "&Terminer"
LangString FINISH_BUTTON 1031 "&Fertig"
LangString FINISH_BUTTON 1034 "&Finalizar"
!define MUI_BUTTONTEXT_FINISH "$(FINISH_BUTTON)"

; ── 语言选择页 ──
LangString LANG_SELECT_TITLE 1033 "Select Language / 选择语言"
LangString LANG_SELECT_TITLE 2052 "选择语言 / Select Language"
LangString LANG_SELECT_TITLE 1041 "言語選択 / Select Language"
LangString LANG_SELECT_TITLE 1042 "언어 선택 / Select Language"
LangString LANG_SELECT_TITLE 1036 "Choisir la langue / Select Language"
LangString LANG_SELECT_TITLE 1031 "Sprache wahlen / Select Language"
LangString LANG_SELECT_TITLE 1034 "Seleccionar idioma / Select Language"

; ── 自定义语言选择页 ──
Var LangDialog
Var LangList
Var SelectedLang

Function LangPageShow
  ; 初始化语言列表
  nsDialogs::Create 1018
  Pop $LangDialog
  ${If} $LangDialog == error
    Abort
  ${EndIf}
  
  nsDialogs::CreateControl "COMBOBOX" ${DEFAULT_STYLES}|${CBS_DROPDOWNLIST} 0 0u 50u 100% 12u ""
  Pop $LangList
  
  ; 添加7种语言
  SendMessage $LangList ${CB_ADDSTRING} 0 "English"
  SendMessage $LangList ${CB_ADDSTRING} 0 "简体中文"
  SendMessage $LangList ${CB_ADDSTRING} 0 "日本語"
  SendMessage $LangList ${CB_ADDSTRING} 0 "한국어"
  SendMessage $LangList ${CB_ADDSTRING} 0 "Deutsch"
  SendMessage $LangList ${CB_ADDSTRING} 0 "Français"
  SendMessage $LangList ${CB_ADDSTRING} 0 "Español"
  
  SendMessage $LangList ${CB_SETCURSEL} 0 0
  
  nsDialogs::Show
FunctionEnd

Function LangPageLeave
  SendMessage $LangList ${CB_GETCURSEL} 0 0 $SelectedLang
  
  ${If} $SelectedLang == 0
    StrCpy $LANGUAGE 1033   ; English
  ${ElseIf} $SelectedLang == 1
    StrCpy $LANGUAGE 2052   ; SimpChinese
  ${ElseIf} $SelectedLang == 2
    StrCpy $LANGUAGE 1041   ; Japanese
  ${ElseIf} $SelectedLang == 3
    StrCpy $LANGUAGE 1042   ; Korean
  ${ElseIf} $SelectedLang == 4
    StrCpy $LANGUAGE 1031   ; German
  ${ElseIf} $SelectedLang == 5
    StrCpy $LANGUAGE 1036   ; French
  ${ElseIf} $SelectedLang == 6
    StrCpy $LANGUAGE 1034   ; Spanish
  ${EndIf}
FunctionEnd

Page custom LangPageShow LangPageLeave "$(LANG_SELECT_TITLE)"

!define MUI_PAGE_HEADER_TEXT "$(WELCOME_TITLE)"
!define MUI_PAGE_HEADER_SUBTEXT "$(DIR_TEXT)"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_TITLE "$(FINISH_TITLE)"
!define MUI_FINISHPAGE_TEXT "$(FINISH_TEXT)"
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

; ── 语言定义必须在最后 ──
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "SimpChinese"
!insertmacro MUI_LANGUAGE "Japanese"
!insertmacro MUI_LANGUAGE "Korean"
!insertmacro MUI_LANGUAGE "German"
!insertmacro MUI_LANGUAGE "French"
!insertmacro MUI_LANGUAGE "Spanish"

Section "MeshCtx Desktop" SecMain
    SetOutPath "$INSTDIR"
    File "dist\meshctx-desktop.exe"
    Rename "$INSTDIR\meshctx-desktop.exe" "$INSTDIR\MeshCtx.exe"
    File "logo.ico"
    
    CreateShortCut "$DESKTOP\MeshCtx.lnk" "$INSTDIR\MeshCtx.exe" "" "$INSTDIR\logo.ico"
    CreateDirectory "$SMPROGRAMS\MeshCtx"
    CreateShortCut "$SMPROGRAMS\MeshCtx\MeshCtx.lnk" "$INSTDIR\MeshCtx.exe" "" "$INSTDIR\logo.ico"
    CreateShortCut "$SMPROGRAMS\MeshCtx\Uninstall.lnk" "$INSTDIR\uninstall.exe"
    
    WriteUninstaller "$INSTDIR\uninstall.exe"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx" "DisplayName" "MeshCtx Desktop"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx" "UninstallString" "$INSTDIR\uninstall.exe"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx" "DisplayIcon" "$INSTDIR\logo.ico"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx" "Publisher" "${PUBLISHER}"
    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx" "DisplayVersion" "${VERSION}"
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx" "NoModify" 1
    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx" "NoRepair" 1
SectionEnd

Section "Uninstall"
    Delete "$INSTDIR\MeshCtx.exe"
    Delete "$INSTDIR\logo.ico"
    Delete "$INSTDIR\uninstall.exe"
    RMDir "$INSTDIR"
    Delete "$DESKTOP\MeshCtx.lnk"
    Delete "$SMPROGRAMS\MeshCtx\MeshCtx.lnk"
    Delete "$SMPROGRAMS\MeshCtx\Uninstall.lnk"
    RMDir "$SMPROGRAMS\MeshCtx"
    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx"
SectionEnd
