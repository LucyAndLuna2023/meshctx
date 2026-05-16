; meshctx Desktop — NSIS Unicode 安装脚本 v2.15.6
; 7语言 + MUI_LANGDLL(原生语言选择,解决乱码)
; ⚠️ LangString内必须用$\n换行，不能用$\\n(会导致乱码)
; 构建: makensis meshctx_setup.nsi
     4|
     5|Unicode true
     6|!include "MUI2.nsh"
     7|!include "FileFunc.nsh"
     8|!include "LogicLib.nsh"
     9|
    10|Name "MeshCtx Desktop"
    11|OutFile "dist\meshctx-setup.exe"
    12|InstallDir "$PROGRAMFILES\MeshCtx"
    13|RequestExecutionLevel admin
    14|SetCompressor /SOLID lzma
    15|
    16|!define VERSION "2.15.6"
    17|!define PUBLISHER "meshctx.com"
    18|
    19|; ── 界面图标 ───────────────────────────────
    20|!define MUI_ABORTWARNING
    21|!define MUI_ICON "logo.ico"
    22|!define MUI_UNICON "logo.ico"
    23|
    24|; ── 7语言欢迎词 (LangString) ──────────────
    25|LangString WELCOME_TITLE 1033 "MeshCtx Desktop v${VERSION}"
    26|LangString WELCOME_TITLE 2052 "MeshCtx 桌面 v${VERSION}"
    27|LangString WELCOME_TITLE 1041 "MeshCtx デスクトップ v${VERSION}"
    28|LangString WELCOME_TITLE 1042 "MeshCtx 데스크탑 v${VERSION}"
    29|LangString WELCOME_TITLE 1036 "MeshCtx Desktop v${VERSION}"
    30|LangString WELCOME_TITLE 1031 "MeshCtx Desktop v${VERSION}"
    31|LangString WELCOME_TITLE 1034 "MeshCtx Escritorio v${VERSION}"
    32|
    33|LangString WELCOME_TEXT 1033 "The first self-evolving AI Agent for Windows.$
$
This wizard will install MeshCtx on your computer.$
$
Click Install to begin."
    34|LangString WELCOME_TEXT 2052 "世界首个自进化AI Agent系统，Windows原生客户端。$
$
本向导将在您的电脑上安装 MeshCtx。$
$
点击 安装 开始。"
    35|LangString WELCOME_TEXT 1041 "世界初の自己進化AIエージェント、Windowsネイティブクライアント。$
$
このウィザードは MeshCtx をインストールします。$
$
インストール をクリックして開始。"
    36|LangString WELCOME_TEXT 1042 "세계 최초 자기진화 AI 에이전트, Windows 네이티브 클라이언트.$
$
이 마법사는 MeshCtx를 설치합니다.$
$
설치를 클릭하여 시작하세요."
    37|LangString WELCOME_TEXT 1036 "Le premier agent IA auto-évolutif pour Windows.$
$
Cet assistant installera MeshCtx sur votre ordinateur.$
$
Cliquez sur Installer pour commencer."
    38|LangString WELCOME_TEXT 1031 "Der erste selbstentwickelnde KI-Agent für Windows.$
$
Dieser Assistent installiert MeshCtx auf Ihrem Computer.$
$
Klicken Sie auf Installieren, um zu beginnen."
    39|LangString WELCOME_TEXT 1034 "El primer agente IA autoevolutivo para Windows.$
$
Este asistente instalará MeshCtx en su equipo.$
$
Haga clic en Instalar para comenzar."
    40|
    41|!define MUI_WELCOMEPAGE_TITLE "$(WELCOME_TITLE)"
    42|!define MUI_WELCOMEPAGE_TEXT "$(WELCOME_TEXT)"
    43|
    44|; ── 7语言目录页提示词 ──────────────────
    45|LangString DIR_TEXT 1033 "Choose install folder.$
$
Setup will install MeshCtx in the following folder.$
To install in a different folder, click Browse."
    46|LangString DIR_TEXT 2052 "选择安装目录。$
$
安装程序将把 MeshCtx 安装到以下目录。$
如需安装到其他目录，请点击浏览。"
    47|LangString DIR_TEXT 1041 "インストール先を選択してください。$
$
MeshCtx を以下のフォルダにインストールします。$
別のフォルダにインストールする場合は、参照をクリック。"
    48|LangString DIR_TEXT 1042 "설치 폴더를 선택하세요.$
$
MeshCtx를 다음 폴더에 설치합니다.$
다른 폴더에 설치하려면 찾아보기를 클릭하세요."
    49|LangString DIR_TEXT 1036 "Choisissez le dossier d'installation.$
$
MeshCtx sera installé dans le dossier suivant.$
Pour un autre dossier, cliquez sur Parcourir."
    50|LangString DIR_TEXT 1031 "Wählen Sie den Installationsordner.$
$
MeshCtx wird im folgenden Ordner installiert.$
Für einen anderen Ordner klicken Sie auf Durchsuchen."
    51|LangString DIR_TEXT 1034 "Elija la carpeta de instalación.$
$
MeshCtx se instalará en la siguiente carpeta.$
Para otra carpeta, haga clic en Examinar."
    52|
    53|!define MUI_DIRECTORYPAGE_TEXT_TOP "$(DIR_TEXT)"
    54|
    55|; ── 页面顺序(语言选择由MUI_LANGDLL处理) ──
    56|!insertmacro MUI_PAGE_WELCOME
    57|!insertmacro MUI_PAGE_DIRECTORY
    58|!insertmacro MUI_PAGE_INSTFILES
    59|!insertmacro MUI_PAGE_FINISH
    60|
    61|!insertmacro MUI_UNPAGE_CONFIRM
    62|!insertmacro MUI_UNPAGE_INSTFILES
    63|
    64|; ── 7语言注册 ─────────────────────────────
    65|!define MUI_LANGDLL_REGISTRY_ROOT "HKLM"
    66|!define MUI_LANGDLL_REGISTRY_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx"
    67|!define MUI_LANGDLL_REGISTRY_VALUENAME "Installer Language"
    68|!define MUI_LANGDLL_ALLLANGUAGES
    69|!insertmacro MUI_LANGUAGE "English"
    70|!insertmacro MUI_LANGUAGE "SimpChinese"
    71|!insertmacro MUI_LANGUAGE "Japanese"
    72|!insertmacro MUI_LANGUAGE "Korean"
    73|!insertmacro MUI_LANGUAGE "German"
    74|!insertmacro MUI_LANGUAGE "French"
    75|!insertmacro MUI_LANGUAGE "Spanish"
    76|
    77|; ── 安装前显示语言选择对话框 ──────────────
    78|Function .onInit
    79|  !insertmacro MUI_LANGDLL_DISPLAY
    80|FunctionEnd
    81|
    82|; ── 安装区段 ──────────────────────────────
    83|Section "MeshCtx Desktop" SecMain
    84|    SetOutPath "$INSTDIR"
    85|    
    86|    File "dist\meshctx-desktop.exe"
    87|    Rename "$INSTDIR\meshctx-desktop.exe" "$INSTDIR\MeshCtx.exe"
    88|    File "logo.ico"
    89|    File "README.md"
    90|    Rename "$INSTDIR\README.md" "$INSTDIR\README.txt"
    91|    
    92|    WriteUninstaller "$INSTDIR\uninstall.exe"
    93|    
    94|    CreateDirectory "$SMPROGRAMS\MeshCtx"
    95|    CreateShortcut "$SMPROGRAMS\MeshCtx\MeshCtx.lnk" "$INSTDIR\MeshCtx.exe" "" "$INSTDIR\logo.ico"
    96|    CreateShortcut "$SMPROGRAMS\MeshCtx\Uninstall.lnk" "$INSTDIR\uninstall.exe"
    97|    
    98|    CreateShortcut "$DESKTOP\MeshCtx.lnk" "$INSTDIR\MeshCtx.exe" "" "$INSTDIR\logo.ico"
    99|    
   100|    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx" \
   101|        "DisplayName" "MeshCtx Desktop"
   102|    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx" \
   103|        "UninstallString" "$INSTDIR\uninstall.exe"
   104|    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx" \
   105|        "DisplayIcon" "$INSTDIR\logo.ico"
   106|    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx" \
   107|        "Publisher" "${PUBLISHER}"
   108|    WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx" \
   109|        "DisplayVersion" "${VERSION}"
   110|    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx" \
   111|        "NoModify" 1
   112|    
   113|    ${GetSize} "$INSTDIR" "/S=0K" $0 $1 $2
   114|    IntFmt $0 "0x%08X" $0
   115|    WriteRegDWORD HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx" \
   116|        "EstimatedSize" "$0"
   117|SectionEnd
   118|
   119|; ── 卸载 ──────────────────────────────────
   120|Section "Uninstall"
   121|    Delete "$INSTDIR\MeshCtx.exe"
   122|    Delete "$INSTDIR\logo.ico"
   123|    Delete "$INSTDIR\README.txt"
   124|    Delete "$INSTDIR\uninstall.exe"
   125|    RMDir "$INSTDIR"
   126|    
   127|    Delete "$SMPROGRAMS\MeshCtx\MeshCtx.lnk"
   128|    Delete "$SMPROGRAMS\MeshCtx\Uninstall.lnk"
   129|    RMDir "$SMPROGRAMS\MeshCtx"
   130|    
   131|    Delete "$DESKTOP\MeshCtx.lnk"
   132|    
   133|    DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\MeshCtx"
   134|SectionEnd
   135|