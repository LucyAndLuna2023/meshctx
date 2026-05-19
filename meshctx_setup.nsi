     1|; meshctx Desktop — NSIS Unicode v2.25.0
     2|; 7语言 + MUI_LANGDLL
     3|; $\n for newlines in LangStrings (NOT $\n)
     4|; 构建: makensis meshctx_setup.nsi
     5|
     6|Unicode true
     7|!include "MUI2.nsh"
     8|!include "FileFunc.nsh"
     9|!include "LogicLib.nsh"
    10|
    11|Name "MeshCtx Desktop"
    12|OutFile "dist\meshctx-setup.exe"
    13|InstallDir "$PROGRAMFILES\MeshCtx"
    14|RequestExecutionLevel admin
    15|SetCompressor /SOLID lzma
    16|
    17|!define VERSION "2.25.0"
    18|!define PUBLISHER "meshctx.com"
    19|
    20|!define MUI_ABORTWARNING
    21|!define MUI_ICON "logo.ico"
    22|!define MUI_UNICON "logo.ico"
    23|
    24|; ── 7语言欢迎词 ──
    25|LangString WELCOME_TITLE 1033 "MeshCtx Desktop v${VERSION}"
    26|LangString WELCOME_TITLE 2052 "MeshCtx 桌面 v${VERSION}"
    27|LangString WELCOME_TITLE 1041 "MeshCtx デスクトップ v${VERSION}"
    28|LangString WELCOME_TITLE 1042 "MeshCtx 데스크탑 v${VERSION}"
    29|LangString WELCOME_TITLE 1036 "MeshCtx Desktop v${VERSION}"
    30|LangString WELCOME_TITLE 1031 "MeshCtx Desktop v${VERSION}"
    31|LangString WELCOME_TITLE 1034 "MeshCtx Escritorio v${VERSION}"
    32|
    33|LangString WELCOME_TEXT 1033 "The first self-evolving AI Agent for Windows.$\n$\nThis wizard will install MeshCtx on your computer.$\n$\nClick Install to begin."
    34|LangString WELCOME_TEXT 2052 "世界首个自进化AI Agent系统，Windows原生客户端。$\n$\n本向导将在您的电脑上安装 MeshCtx。$\n$\n点击 安装 开始。"
    35|LangString WELCOME_TEXT 1041 "世界初の自己進化AIエージェント、Windowsネイティブクライアント。$\n$\nこのウィザードは MeshCtx をインストールします。$\n$\nインストール をクリックして開始。"
    36|LangString WELCOME_TEXT 1042 "세계 최초 자기진화 AI 에이전트, Windows 네이티브 클라이언트.$\n$\n이 마법사는 MeshCtx를 설치합니다.$\n$\n설치를 클릭하여 시작하세요."
    37|LangString WELCOME_TEXT 1036 "Le premier agent IA auto-evolutif pour Windows.$\n$\nCet assistant installera MeshCtx sur votre ordinateur.$\n$\nCliquez sur Installer pour commencer."
    38|LangString WELCOME_TEXT 1031 "Der erste selbstentwickelnde KI-Agent fur Windows.$\n$\nDieser Assistent installiert MeshCtx auf Ihrem Computer.$\n$\nKlicken Sie auf Installieren, um zu beginnen."
    39|LangString WELCOME_TEXT 1034 "El primer agente IA autoevolutivo para Windows.$\n$\nEste asistente instalara MeshCtx en su equipo.$\n$\nHaga clic en Instalar para comenzar."
    40|
    41|!define MUI_WELCOMEPAGE_TITLE "$(WELCOME_TITLE)"
    42|!define MUI_WELCOMEPAGE_TEXT "$(WELCOME_TEXT)"
    43|
    44|; ── 7语言目录页 ──
    45|LangString DIR_TEXT 1033 "Choose install folder.$\n$\nSetup will install MeshCtx in the following folder.$\nTo install in a different folder, click Browse."
    46|LangString DIR_TEXT 2052 "选择安装目录。$\n$\n安装程序将把 MeshCtx 安装到以下目录。$\n如需安装到其他目录，请点击浏览。"
    47|LangString DIR_TEXT 1041 "インストール先を選択してください。$\n$\nMeshCtx を以下のフォルダにインストールします。$\n別のフォルダにインストールする場合は、参照をクリック。"
    48|LangString DIR_TEXT 1042 "설치 폴더를 선택하세요.$\n$\nMeshCtx를 다음 폴더에 설치합니다.$\n다른 폴더에 설치하려면 찾아보기를 클릭하세요."
    49|LangString DIR_TEXT 1036 "Choisissez le dossier d'installation.$\n$\nMeshCtx sera installe dans le dossier suivant.$\nPour un autre dossier, cliquez sur Parcourir."
    50|LangString DIR_TEXT 1031 "Wahlen Sie den Installationsordner.$\n$\nMeshCtx wird im folgenden Ordner installiert.$\nFur einen anderen Ordner klicken Sie auf Durchsuchen."
    51|LangString DIR_TEXT 1034 "Elija la carpeta de instalacion.$\n$\nMeshCtx se instalara en la siguiente carpeta.$\nPara otra carpeta, haga clic en Examinar."
    52|
    53|!define MUI_DIRECTORYPAGE_TEXT_TOP "$(DIR_TEXT)"
    54|
    55|; ── 7语言安装/完成页 ──
    56|LangString INSTALLING 1033 "Installing MeshCtx..."
    57|LangString INSTALLING 2052 "正在安装 MeshCtx..."
    58|LangString INSTALLING 1041 "MeshCtx をインストール中..."
    59|LangString INSTALLING 1042 "MeshCtx 설치 중..."
    60|LangString INSTALLING 1036 "Installation de MeshCtx..."
    61|LangString INSTALLING 1031 "MeshCtx wird installiert..."
    62|LangString INSTALLING 1034 "Instalando MeshCtx..."
    63|
    64|LangString FINISH_TITLE 1033 "Installation Complete"
    65|LangString FINISH_TITLE 2052 "安装完成"
    66|LangString FINISH_TITLE 1041 "インストール完了"
    67|LangString FINISH_TITLE 1042 "설치 완료"
    68|LangString FINISH_TITLE 1036 "Installation terminee"
    69|LangString FINISH_TITLE 1031 "Installation abgeschlossen"
    70|LangString FINISH_TITLE 1034 "Instalacion completada"
    71|
    72|LangString FINISH_TEXT 1033 "MeshCtx has been installed.$\n$\nStart from Start Menu or Desktop shortcut.$\n$\nRun 'meshctx setup' to configure your API key."
    73|LangString FINISH_TEXT 2052 "MeshCtx 安装完成。$\n$\n从开始菜单或桌面快捷方式启动。$\n$\n运行 'meshctx setup' 配置API密钥。"
    74|LangString FINISH_TEXT 1041 "MeshCtx のインストールが完了しました。$\n$\nスタートメニューまたはデスクトップから起動してください。$\n$\n'meshctx setup' でAPIキーを設定。"
    75|LangString FINISH_TEXT 1042 "MeshCtx 설치가 완료되었습니다.$\n$\n시작 메뉴 또는 바탕화면에서 실행하세요.$\n$\n'meshctx setup'으로 API 키를 설정하세요."
    76|LangString FINISH_TEXT 1036 "MeshCtx a ete installe.$\n$\nLancez depuis le menu Demarrer ou le bureau.$\n$\nLancez 'meshctx setup' pour configurer votre cle API."
    77|LangString FINISH_TEXT 1031 "MeshCtx wurde installiert.$\n$\nStarten Sie uber das Startmenu oder die Desktop-Verknupfung.$\n$\nFuhren Sie 'meshctx setup' aus, um Ihren API-Schlussel zu konfigurieren."
    78|LangString FINISH_TEXT 1034 "MeshCtx se ha instalado.$\n$\nInicie desde el menu Inicio o el acceso directo del escritorio.$\n$\nEjecute 'meshctx setup' para configurar su clave API."
    79|
    80|!define MUI_FINISHPAGE_TITLE "$(FINISH_TITLE)"
    81|!define MUI_FINISHPAGE_TEXT "$(FINISH_TEXT)"
    82|!define MUI_INSTFILESPAGE_FINISHHEADER_TEXT "$(INSTALLING)"
    83|
    84|; ── 页面顺序 ──
    85|!insertmacro MUI_PAGE_WELCOME
    86|!insertmacro MUI_PAGE_DIRECTORY
    87|!insertmacro MUI_PAGE_INSTFILES
    88|!insertmacro MUI_PAGE_FINISH
    89|
    90|!insertmacro MUI_UNPAGE_CONFIRM
    91|!insertmacro MUI_UNPAGE_INSTFILES
    92|
    93|; ── 7语言注册 ──
    94|!define MUI_LANGDLL_REGISTRY_ROOT "HKLM"
    95|!define MUI_LANGDLL_REGISTRY_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx"
    96|!define MUI_LANGDLL_REGISTRY_VALUENAME "Installer Language"
    97|!define MUI_LANGDLL_ALLLANGUAGES
    98|!insertmacro MUI_LANGUAGE "English"
    99|!insertmacro MUI_LANGUAGE "SimpChinese"
   100|!insertmacro MUI_LANGUAGE "Japanese"
   101|!insertmacro MUI_LANGUAGE "Korean"
   102|!insertmacro MUI_LANGUAGE "German"
   103|!insertmacro MUI_LANGUAGE "French"
   104|!insertmacro MUI_LANGUAGE "Spanish"
   105|
   106|Function .onInit
   107|  !insertmacro MUI_LANGDLL_DISPLAY
   108|FunctionEnd
   109|
   110|; ── 安装(用户数据保留在 %USERPROFILE%\.meshctx) ──
   111|Section "MeshCtx Desktop" SecMain
   112|    SetOutPath "$INSTDIR"
   113|    File "dist\meshctx-desktop.exe"
   114|    Rename "$INSTDIR\meshctx-desktop.exe" "$INSTDIR\MeshCtx.exe"
   115|    File "logo.ico"
   116|    File "README.md"
   117|    Rename "$INSTDIR\README.md" "$INSTDIR\README.txt"
   118|    
   119|    WriteUninstaller "$INSTDIR\uninstall.exe"
   120|    
   121|    CreateDirectory "$SMPROGRAMS\MeshCtx"
   122|    CreateShortcut "$SMPROGRAMS\MeshCtx\MeshCtx.lnk" "$INSTDIR\MeshCtx.exe" "" "$INSTDIR\logo.ico"
   123|    CreateShortcut "$SMPROGRAMS\MeshCtx\Uninstall.lnk" "$INSTDIR\uninstall.exe"
   124|    
   125|    CreateShortcut "$DESKTOP\MeshCtx.lnk" "$INSTDIR\MeshCtx.exe" "" "$INSTDIR\logo.ico"
   126|    
   127|    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx" \
   128|        "DisplayName" "MeshCtx Desktop"
   129|    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx" \
   130|        "UninstallString" "$INSTDIR\uninstall.exe"
   131|    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx" \
   132|        "DisplayIcon" "$INSTDIR\logo.ico"
   133|    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx" \
   134|        "Publisher" "${PUBLISHER}"
   135|    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx" \
   136|        "DisplayVersion" "${VERSION}"
   137|    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx" \
   138|        "NoModify" 1
   139|    
   140|    ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
   141|    IntFmt $0 "0x%08X" $0
   142|    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx" \
   143|        "EstimatedSize" "$0"
   144|SectionEnd
   145|
   146|; ── 卸载(只删程序,保留用户数据) ──
   147|Section "Uninstall"
   148|    Delete "$INSTDIR\MeshCtx.exe"
   149|    Delete "$INSTDIR\logo.ico"
   150|    Delete "$INSTDIR\README.txt"
   151|    Delete "$INSTDIR\uninstall.exe"
   152|    RMDir "$INSTDIR"
   153|    
   154|    Delete "$SMPROGRAMS\MeshCtx\MeshCtx.lnk"
   155|    Delete "$SMPROGRAMS\MeshCtx\Uninstall.lnk"
   156|    RMDir "$SMPROGRAMS\MeshCtx"
   157|    
   158|    Delete "$DESKTOP\MeshCtx.lnk"
   159|    
   160|    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx"
   161|SectionEnd
   162|