@echo off
REM meshctx Windows Installer v5 — from GitHub Releases
REM i18n: set MESHCTX_LANG=zh|en|ja|ko|fr|de|es|it|ar (default: en)
title meshctx Installer
setlocal enabledelayedexpansion

set "INSTALL_DIR=%USERPROFILE%\.meshctx"
set "VERSION=3.120.5"
set "SRC_URL=https://github.com/LucyAndLuna2023/meshctx/archive/refs/tags/v%VERSION%.tar.gz"
set "PORTABLE_URL=https://github.com/LucyAndLuna2023/meshctx/releases/download/v%VERSION%/meshctx-windows-cli.zip"

REM ── i18n (9 languages: zh/en/ja/ko/fr/de/es/it/ar) ────────
if "%MESHCTX_LANG%"=="" set "MESHCTX_LANG=en"
set "_T_HEADER=meshctx v%VERSION% One-Click Install"
set "_T_STEP_CHECK=Checking environment..."
set "_T_STEP_DOWNLOAD=Downloading meshctx v%VERSION%..."
set "_T_STEP_EXTRACT=Extracting..."
set "_T_STEP_DEPS=Installing dependencies..."
set "_T_PYTHON_MISSING=Requires Python 3.10+, install from python.org"
set "_T_DOWNLOAD_FAIL=Download failed. Check network, or use WSL"
set "_T_EXTRACT_FAIL=Extraction failed. Win10 1803+ required"
set "_T_DONE=Installation complete. Run:"
set "_T_PORTABLE_DL=Downloading full portable build with closed-source core included..."
set "_T_PORTABLE_OK=Full portable asset ready, no Python needed"
set "_T_PORTABLE_WARN=Portable asset unavailable, fallback to source install..."
set "_T_EXTRACT_PORTABLE=Extracting portable..."
set "_T_EXE_MISSING=meshctx.exe missing in portable asset"
set "_T_CORE_EMBEDDED=Closed-source core embedded, full portable build, no Python needed"
set "_T_CORE_INSTALL=Installing closed-source core meshctx-core ..."
set "_T_CORE_OK=Closed-source core installed as one product, full build"
set "_T_CORE_FAIL=Failed to fetch closed-source core, token or network issue. Full product must include the core, stub install forbidden"
set "_T_GIT_MISSING=git not installed. Source install mode needs git plus MESHCTX_CORE_TOKEN for the closed-source core"
set "_T_HINT_SETUP=Use the official installer meshctx-setup.exe which includes the closed-source core, or install git, set MESHCTX_CORE_TOKEN and re-run"
set "_T_TOKEN_MISSING=MESHCTX_CORE_TOKEN not provided. Full product must include the closed-source core, stub install forbidden"
set "_T_HINT_TOKEN=Use the official installer meshctx-setup.exe which includes the closed-source core, or set MESHCTX_CORE_TOKEN and re-run"
set "_T_WEBUI=Web UI:"
if /i "%MESHCTX_LANG%"=="zh" (
    set "_T_HEADER=meshctx v%VERSION% 一键安装"
    set "_T_STEP_CHECK=检查环境..."
    set "_T_STEP_DOWNLOAD=下载 meshctx v%VERSION%..."
    set "_T_STEP_EXTRACT=解压中..."
    set "_T_STEP_DEPS=安装依赖中..."
    set "_T_PYTHON_MISSING=需要 Python 3.10+，请从 python.org 安装"
    set "_T_DOWNLOAD_FAIL=下载失败。请检查网络，或使用 WSL"
    set "_T_EXTRACT_FAIL=解压失败。需要 Win10 1803+"
    set "_T_DONE=安装完成。运行："
    set "_T_PORTABLE_DL=正在下载完整便携版（含闭源核心）..."
    set "_T_PORTABLE_OK=完整便携资产就绪，无需 Python"
    set "_T_PORTABLE_WARN=便携资产不可用，回退源码安装..."
    set "_T_EXTRACT_PORTABLE=正在解压便携版..."
    set "_T_EXE_MISSING=便携资产中缺少 meshctx.exe"
    set "_T_CORE_EMBEDDED=已内置闭源核心，完整便携版，无需 Python"
    set "_T_CORE_INSTALL=正在安装闭源核心 meshctx-core ..."
    set "_T_CORE_OK=闭源核心已随完整产品安装"
    set "_T_CORE_FAIL=获取闭源核心失败（token 或网络问题）。完整产品必须包含核心，禁止桩安装"
    set "_T_GIT_MISSING=未安装 git。源码安装模式需要 git 和 MESHCTX_CORE_TOKEN 获取闭源核心"
    set "_T_HINT_SETUP=请使用官方安装器 meshctx-setup.exe（含闭源核心），或安装 git、设置 MESHCTX_CORE_TOKEN 后重试"
    set "_T_TOKEN_MISSING=未提供 MESHCTX_CORE_TOKEN。完整产品必须包含闭源核心，禁止桩安装"
    set "_T_HINT_TOKEN=请使用官方安装器 meshctx-setup.exe（含闭源核心），或设置 MESHCTX_CORE_TOKEN 后重试"
    set "_T_WEBUI=网页界面："
)
if /i "%MESHCTX_LANG%"=="ja" (
    set "_T_HEADER=meshctx v%VERSION% ワンクリックインストール"
    set "_T_STEP_CHECK=環境を確認中..."
    set "_T_STEP_DOWNLOAD=meshctx v%VERSION% をダウンロード中..."
    set "_T_STEP_EXTRACT=展開中..."
    set "_T_STEP_DEPS=依存関係をインストール中..."
    set "_T_PYTHON_MISSING=Python 3.10+ が必要です。python.org からインストールしてください"
    set "_T_DOWNLOAD_FAIL=ダウンロード失敗。ネットワークを確認するか WSL を使用してください"
    set "_T_EXTRACT_FAIL=展開失敗。Win10 1803+ が必要です"
    set "_T_DONE=インストール完了。実行："
    set "_T_PORTABLE_DL=完全ポータブル版をダウンロード中（クローズドソースコア含む）..."
    set "_T_PORTABLE_OK=完全ポータブルアセット準備完了、Python 不要"
    set "_T_PORTABLE_WARN=ポータブルアセットが利用できないため、ソースインストールに切り替えます..."
    set "_T_EXTRACT_PORTABLE=ポータブル版を展開中..."
    set "_T_EXE_MISSING=ポータブルアセットに meshctx.exe がありません"
    set "_T_CORE_EMBEDDED=クローズドソースコアを内蔵、完全ポータブル版、Python 不要"
    set "_T_CORE_INSTALL=クローズドソースコア meshctx-core をインストール中..."
    set "_T_CORE_OK=クローズドソースコアを一体製品としてインストール完了"
    set "_T_CORE_FAIL=クローズドソースコアの取得に失敗しました（token またはネットワークの問題）。完全製品にはコアが必須で、スタブインストールは禁止です"
    set "_T_GIT_MISSING=git がインストールされていません。ソースインストールモードには git と MESHCTX_CORE_TOKEN が必要です"
    set "_T_HINT_SETUP=公式インストーラー meshctx-setup.exe（クローズドソースコア含む）を使用するか、git をインストールして MESHCTX_CORE_TOKEN を設定し再実行してください"
    set "_T_TOKEN_MISSING=MESHCTX_CORE_TOKEN が設定されていません。完全製品にはクローズドソースコアが必須で、スタブインストールは禁止です"
    set "_T_HINT_TOKEN=公式インストーラー meshctx-setup.exe（クローズドソースコア含む）を使用するか、MESHCTX_CORE_TOKEN を設定して再実行してください"
    set "_T_WEBUI=Web UI:"
)
if /i "%MESHCTX_LANG%"=="ko" (
    set "_T_HEADER=meshctx v%VERSION% 원클릭 설치"
    set "_T_STEP_CHECK=환경 확인 중..."
    set "_T_STEP_DOWNLOAD=meshctx v%VERSION% 다운로드 중..."
    set "_T_STEP_EXTRACT=압축 해제 중..."
    set "_T_STEP_DEPS=의존성 설치 중..."
    set "_T_PYTHON_MISSING=Python 3.10+ 필요, python.org에서 설치하세요"
    set "_T_DOWNLOAD_FAIL=다운로드 실패. 네트워크를 확인하거나 WSL을 사용하세요"
    set "_T_EXTRACT_FAIL=압축 해제 실패. Win10 1803+ 필요"
    set "_T_DONE=설치 완료. 실행："
    set "_T_PORTABLE_DL=전체 포터블 빌드 다운로드 중（클로즈드 소스 코어 포함）..."
    set "_T_PORTABLE_OK=전체 포터블 에셋 준비 완료, Python 불필요"
    set "_T_PORTABLE_WARN=포터블 에셋을 사용할 수 없어 소스 설치로 대체합니다..."
    set "_T_EXTRACT_PORTABLE=포터블 버전 압축 해제 중..."
    set "_T_EXE_MISSING=포터블 에셋에 meshctx.exe 없음"
    set "_T_CORE_EMBEDDED=클로즈드 소스 코어 내장, 전체 포터블 빌드, Python 불필요"
    set "_T_CORE_INSTALL=클로즈드 소스 코어 meshctx-core 설치 중..."
    set "_T_CORE_OK=클로즈드 소스 코어가 통합 제품으로 설치됨"
    set "_T_CORE_FAIL=클로즈드 소스 코어 가져오기 실패（token 또는 네트워크 문제）。정식 제품에는 코어가 필수이며 스텁 설치는 금지입니다"
    set "_T_GIT_MISSING=git이 설치되지 않았습니다. 소스 설치 모드에는 git과 MESHCTX_CORE_TOKEN이 필요합니다"
    set "_T_HINT_SETUP=공식 설치 프로그램 meshctx-setup.exe（클로즈드 소스 코어 포함）를 사용하거나 git을 설치하고 MESHCTX_CORE_TOKEN을 설정한 후 다시 실행하세요"
    set "_T_TOKEN_MISSING=MESHCTX_CORE_TOKEN이 제공되지 않았습니다. 정식 제품에는 클로즈드 소스 코어가 필수이며 스텁 설치는 금지입니다"
    set "_T_HINT_TOKEN=공식 설치 프로그램 meshctx-setup.exe（클로즈드 소스 코어 포함）를 사용하거나 MESHCTX_CORE_TOKEN을 설정한 후 다시 실행하세요"
    set "_T_WEBUI=웹 UI:"
)
if /i "%MESHCTX_LANG%"=="fr" (
    set "_T_HEADER=meshctx v%VERSION% Installation en un clic"
    set "_T_STEP_CHECK=Vérification de l'environnement..."
    set "_T_STEP_DOWNLOAD=Téléchargement de meshctx v%VERSION%..."
    set "_T_STEP_EXTRACT=Extraction en cours..."
    set "_T_STEP_DEPS=Installation des dépendances..."
    set "_T_PYTHON_MISSING=Python 3.10+ requis, installez depuis python.org"
    set "_T_DOWNLOAD_FAIL=Échec du téléchargement. Vérifiez le réseau, ou utilisez WSL"
    set "_T_EXTRACT_FAIL=Échec de l'extraction. Win10 1803+ requis"
    set "_T_DONE=Installation terminée. Exécutez :"
    set "_T_PORTABLE_DL=Téléchargement du build portable complet avec le noyau closed-source..."
    set "_T_PORTABLE_OK=Asset portable complet prêt, pas de Python requis"
    set "_T_PORTABLE_WARN=Asset portable indisponible, repli sur l'installation depuis les sources..."
    set "_T_EXTRACT_PORTABLE=Extraction de la version portable..."
    set "_T_EXE_MISSING=meshctx.exe manquant dans l'asset portable"
    set "_T_CORE_EMBEDDED=Noyau closed-source intégré, build portable complet, pas de Python requis"
    set "_T_CORE_INSTALL=Installation du noyau closed-source meshctx-core..."
    set "_T_CORE_OK=Noyau closed-source installé comme produit unique"
    set "_T_CORE_FAIL=Échec de récupération du noyau closed-source, problème de token ou de réseau. Le produit complet doit inclure le noyau, l'installation partielle est interdite"
    set "_T_GIT_MISSING=git non installé. Le mode source nécessite git et MESHCTX_CORE_TOKEN pour le noyau closed-source"
    set "_T_HINT_SETUP=Utilisez l'installateur officiel meshctx-setup.exe qui inclut le noyau closed-source, ou installez git, définissez MESHCTX_CORE_TOKEN et relancez"
    set "_T_TOKEN_MISSING=MESHCTX_CORE_TOKEN non fourni. Le produit complet doit inclure le noyau closed-source, installation partielle interdite"
    set "_T_HINT_TOKEN=Utilisez l'installateur officiel meshctx-setup.exe qui inclut le noyau closed-source, ou définissez MESHCTX_CORE_TOKEN et relancez"
    set "_T_WEBUI=Interface web :"
)
if /i "%MESHCTX_LANG%"=="de" (
    set "_T_HEADER=meshctx v%VERSION% Ein-Klick-Installation"
    set "_T_STEP_CHECK=Umgebung wird geprüft..."
    set "_T_STEP_DOWNLOAD=meshctx v%VERSION% wird heruntergeladen..."
    set "_T_STEP_EXTRACT=Entpacken..."
    set "_T_STEP_DEPS=Abhängigkeiten werden installiert..."
    set "_T_PYTHON_MISSING=Python 3.10+ erforderlich, von python.org installieren"
    set "_T_DOWNLOAD_FAIL=Download fehlgeschlagen. Netzwerk prüfen oder WSL verwenden"
    set "_T_EXTRACT_FAIL=Entpacken fehlgeschlagen. Win10 1803+ erforderlich"
    set "_T_DONE=Installation abgeschlossen. Ausführen:"
    set "_T_PORTABLE_DL=Vollständigen tragbaren Build herunterladen, inklusive Closed-Source-Kern..."
    set "_T_PORTABLE_OK=Vollständiger portabler Build bereit, kein Python nötig"
    set "_T_PORTABLE_WARN=Portables Asset nicht verfügbar, Rückfall auf Quellinstallation..."
    set "_T_EXTRACT_PORTABLE=Portable Version wird entpackt..."
    set "_T_EXE_MISSING=meshctx.exe fehlt im portablen Asset"
    set "_T_CORE_EMBEDDED=Closed-Source-Kern eingebettet, vollständiger portabler Build, kein Python nötig"
    set "_T_CORE_INSTALL=Closed-Source-Kern meshctx-core wird installiert..."
    set "_T_CORE_OK=Closed-Source-Kern als ein Produkt installiert"
    set "_T_CORE_FAIL=Abruf des Closed-Source-Kerns fehlgeschlagen, Token- oder Netzwerkproblem. Das vollständige Produkt muss den Kern enthalten, Stub-Installation verboten"
    set "_T_GIT_MISSING=git nicht installiert. Quellmodus benötigt git und MESHCTX_CORE_TOKEN für den Kern"
    set "_T_HINT_SETUP=Verwenden Sie das offizielle Installationsprogramm meshctx-setup.exe mit dem Closed-Source-Kern, oder installieren Sie git, setzen Sie MESHCTX_CORE_TOKEN und führen Sie es erneut aus"
    set "_T_TOKEN_MISSING=MESHCTX_CORE_TOKEN fehlt. Das vollständige Produkt muss den Closed-Source-Kern enthalten, Stub-Installation verboten"
    set "_T_HINT_TOKEN=Verwenden Sie das offizielle Installationsprogramm meshctx-setup.exe mit dem Closed-Source-Kern, oder setzen Sie MESHCTX_CORE_TOKEN und führen Sie es erneut aus"
    set "_T_WEBUI=Web-UI:"
)
if /i "%MESHCTX_LANG%"=="es" (
    set "_T_HEADER=meshctx v%VERSION% Instalación en un clic"
    set "_T_STEP_CHECK=Comprobando entorno..."
    set "_T_STEP_DOWNLOAD=Descargando meshctx v%VERSION%..."
    set "_T_STEP_EXTRACT=Extrayendo..."
    set "_T_STEP_DEPS=Instalando dependencias..."
    set "_T_PYTHON_MISSING=Requiere Python 3.10+, instale desde python.org"
    set "_T_DOWNLOAD_FAIL=Descarga fallida. Compruebe la red, o use WSL"
    set "_T_EXTRACT_FAIL=Error de extracción. Se requiere Win10 1803+"
    set "_T_DONE=Instalación completa. Ejecute:"
    set "_T_PORTABLE_DL=Descargando el build portable completo, con núcleo de código cerrado..."
    set "_T_PORTABLE_OK=Asset portátil completo listo, sin necesidad de Python"
    set "_T_PORTABLE_WARN=Asset portátil no disponible, se usará instalación desde código fuente..."
    set "_T_EXTRACT_PORTABLE=Extrayendo versión portátil..."
    set "_T_EXE_MISSING=Falta meshctx.exe en el asset portátil"
    set "_T_CORE_EMBEDDED=Núcleo de código cerrado integrado, build portátil completo, sin Python"
    set "_T_CORE_INSTALL=Instalando el núcleo de código cerrado meshctx-core..."
    set "_T_CORE_OK=Núcleo de código cerrado instalado como producto único"
    set "_T_CORE_FAIL=Error al obtener el núcleo de código cerrado, problema de token o red. El producto completo debe incluir el núcleo, instalación parcial prohibida"
    set "_T_GIT_MISSING=git no instalado. El modo fuente necesita git y MESHCTX_CORE_TOKEN para el núcleo"
    set "_T_HINT_SETUP=Use el instalador oficial meshctx-setup.exe que incluye el núcleo, o instale git, configure MESHCTX_CORE_TOKEN y vuelva a ejecutar"
    set "_T_TOKEN_MISSING=MESHCTX_CORE_TOKEN no proporcionado. El producto completo debe incluir el núcleo, instalación parcial prohibida"
    set "_T_HINT_TOKEN=Use el instalador oficial meshctx-setup.exe que incluye el núcleo, o configure MESHCTX_CORE_TOKEN y vuelva a ejecutar"
    set "_T_WEBUI=Interfaz web:"
)
if /i "%MESHCTX_LANG%"=="it" (
    set "_T_HEADER=meshctx v%VERSION% Installazione con un clic"
    set "_T_STEP_CHECK=Verifica dell'ambiente in corso..."
    set "_T_STEP_DOWNLOAD=Scaricamento di meshctx v%VERSION% in corso..."
    set "_T_STEP_EXTRACT=Estrazione in corso..."
    set "_T_STEP_DEPS=Installazione delle dipendenze..."
    set "_T_PYTHON_MISSING=Richiede Python 3.10+, installa da python.org"
    set "_T_DOWNLOAD_FAIL=Download fallito. Controlla la rete, o usa WSL"
    set "_T_EXTRACT_FAIL=Estrazione fallita. Richiesto Win10 1803+"
    set "_T_DONE=Installazione completata. Esegui:"
    set "_T_PORTABLE_DL=Scaricamento del build portabile completo, incluso il core closed-source..."
    set "_T_PORTABLE_OK=Asset portatile completo pronto, Python non richiesto"
    set "_T_PORTABLE_WARN=Asset portatile non disponibile, ripiego sull'installazione da sorgente..."
    set "_T_EXTRACT_PORTABLE=Estrazione della versione portatile..."
    set "_T_EXE_MISSING=meshctx.exe mancante nell'asset portatile"
    set "_T_CORE_EMBEDDED=Core closed-source integrato, build portatile completo, Python non richiesto"
    set "_T_CORE_INSTALL=Installazione del core closed-source meshctx-core..."
    set "_T_CORE_OK=Core closed-source installato come prodotto unico"
    set "_T_CORE_FAIL=Recupero del core closed-source fallito, problema di token o rete. Il prodotto completo deve includere il core, installazione stub vietata"
    set "_T_GIT_MISSING=git non installato. La modalità sorgente richiede git e MESHCTX_CORE_TOKEN per il core"
    set "_T_HINT_SETUP=Usare l'installer ufficiale meshctx-setup.exe che include il core, oppure installare git, impostare MESHCTX_CORE_TOKEN e riprovare"
    set "_T_TOKEN_MISSING=MESHCTX_CORE_TOKEN non fornito. Il prodotto completo deve includere il core, installazione stub vietata"
    set "_T_HINT_TOKEN=Usare l'installer ufficiale meshctx-setup.exe che include il core, oppure impostare MESHCTX_CORE_TOKEN e riprovare"
    set "_T_WEBUI=Interfaccia web:"
)
if /i "%MESHCTX_LANG%"=="ar" (
    set "_T_HEADER=meshctx v%VERSION% تثبيت بنقرة واحدة"
    set "_T_STEP_CHECK=التحقق من البيئة..."
    set "_T_STEP_DOWNLOAD=جاري تنزيل meshctx v%VERSION%..."
    set "_T_STEP_EXTRACT=جاري فك الضغط..."
    set "_T_STEP_DEPS=جاري تثبيت التبعيات..."
    set "_T_PYTHON_MISSING=يتطلب Python 3.10+، ثبّت من python.org"
    set "_T_DOWNLOAD_FAIL=فشل التنزيل. تحقق من الشبكة أو استخدم WSL"
    set "_T_EXTRACT_FAIL=فشل فك الضغط. يتطلب Win10 1803+"
    set "_T_DONE=اكتمل التثبيت. شغّل:"
    set "_T_PORTABLE_DL=جاري تنزيل النسخة المحمولة الكاملة بما في ذلك النواة مغلقة المصدر..."
    set "_T_PORTABLE_OK=أصل محمول كامل جاهز، لا حاجة إلى بايثون"
    set "_T_PORTABLE_WARN=الأصل المحمول غير متوفر، سيتم التثبيت من المصدر..."
    set "_T_EXTRACT_PORTABLE=جاري فك ضغط النسخة المحمولة..."
    set "_T_EXE_MISSING=meshctx.exe مفقود في الأصل المحمول"
    set "_T_CORE_EMBEDDED=تم تضمين النواة مغلقة المصدر، نسخة محمولة كاملة، لا حاجة لبايثون"
    set "_T_CORE_INSTALL=جاري تثبيت النواة مغلقة المصدر meshctx-core..."
    set "_T_CORE_OK=تم تثبيت النواة مغلقة المصدر كمنتج واحد"
    set "_T_CORE_FAIL=فشل الحصول على النواة مغلقة المصدر، مشكلة في الرمز أو الشبكة. يجب أن يتضمن المنتج الكامل النواة، التثبيت الجزئي محظور"
    set "_T_GIT_MISSING=git غير مثبت. وضع التثبيت من المصدر يتطلب git و MESHCTX_CORE_TOKEN"
    set "_T_HINT_SETUP=استخدم المثبت الرسمي meshctx-setup.exe الذي يتضمن النواة، أو ثبّت git وحدد MESHCTX_CORE_TOKEN ثم أعد التشغيل"
    set "_T_TOKEN_MISSING=MESHCTX_CORE_TOKEN غير مقدم. يجب أن يتضمن المنتج الكامل النواة مغلقة المصدر، التثبيت الجزئي محظور"
    set "_T_HINT_TOKEN=استخدم المثبت الرسمي meshctx-setup.exe الذي يتضمن النواة، أو حدد MESHCTX_CORE_TOKEN ثم أعد التشغيل"
    set "_T_WEBUI=واجهة الويب:"
)

echo.
echo   %_T_HEADER%
echo   ============================
echo.

set "TMPDIR=%TEMP%\meshctx_%RANDOM%"
mkdir "%TMPDIR%" 2>nul

REM ── [1/4] 完整版封装资产优先（护城河: 含闭源核心, 免 Python）──
set "PORTABLE_OK="
set "PORTABLE_TARBALL=%TMPDIR%\meshctx-windows-cli.zip"
echo [1/4] %_T_PORTABLE_DL%
curl -fsSL --connect-timeout 60 --max-time 900 -o "%PORTABLE_TARBALL%" "%PORTABLE_URL%" 2>nul
if exist "%PORTABLE_TARBALL%" (
    tar -tf "%PORTABLE_TARBALL%" >nul 2>nul
    if not errorlevel 1 set "PORTABLE_OK=1"
)
if defined PORTABLE_OK (
    echo   [OK] %_T_PORTABLE_OK%
) else (
    echo   [WARN] %_T_PORTABLE_WARN%
)

REM ── [2/4] 安装 ───────────────────────────────────────
if defined PORTABLE_OK (
    echo [2/4] %_T_EXTRACT_PORTABLE%
    if exist "%INSTALL_DIR%" rmdir /s /q "%INSTALL_DIR%"
    mkdir "%INSTALL_DIR%"
    powershell -Command "tar -xf '%PORTABLE_TARBALL%' -C '%INSTALL_DIR%'" 2>nul || (
        echo   %_T_EXTRACT_FAIL%
        rmdir /s /q "%TMPDIR%" 2>nul
        pause
        exit /b 1
    )
    if not exist "%INSTALL_DIR%\meshctx\meshctx.exe" (
        echo   [ERROR] %_T_EXE_MISSING%
        rmdir /s /q "%TMPDIR%" 2>nul
        pause
        exit /b 1
    )
    REM 命令行 wrapper
    > "%INSTALL_DIR%\meshctx.cmd" echo @echo off
    >> "%INSTALL_DIR%\meshctx.cmd" echo "%%~dp0meshctx\meshctx.exe" %%*
    rmdir /s /q "%TMPDIR%" 2>nul
    echo   [OK] %_T_CORE_EMBEDDED%
    goto :done
)

REM ── 源码安装模式（需 Python + MESHCTX_CORE_TOKEN）────
echo [1/4] %_T_STEP_CHECK%
where python >nul 2>nul || (echo   %_T_PYTHON_MISSING% && pause && exit /b 1)
echo   OK

echo [2/4] %_T_STEP_DOWNLOAD%
curl -fsSL --connect-timeout 60 -o "%TMPDIR%\meshctx-src.tar.gz" "%SRC_URL%" 2>nul || (
    echo   %_T_DOWNLOAD_FAIL%
    rmdir /s /q "%TMPDIR%" 2>nul
    pause
    exit /b 1
)
echo   OK

echo [3/4] %_T_STEP_EXTRACT%
if exist "%INSTALL_DIR%" rmdir /s /q "%INSTALL_DIR%"
mkdir "%INSTALL_DIR%"
powershell -Command "tar -xzf '%TMPDIR%\meshctx-src.tar.gz' -C '%INSTALL_DIR%' --strip-components=1" 2>nul || (
    echo   %_T_EXTRACT_FAIL%
    rmdir /s /q "%TMPDIR%" 2>nul
    pause
    exit /b 1
)
rmdir /s /q "%TMPDIR%" 2>nul
echo   OK

echo [4/4] %_T_STEP_DEPS%
cd /d "%INSTALL_DIR%"
if not exist "venv" python -m venv venv
call venv\Scripts\activate.bat
pip install -q fastapi uvicorn pydantic numpy openai jinja2 httpx pyyaml aiofiles packaging 2>nul
echo   OK

REM ── [5/5] 闭源核心组件 (meshctx-core · 一体产品) ─────
echo [5/5] %_T_CORE_INSTALL%
set "CORE_CLONE_OK="
if not defined MESHCTX_CORE_TOKEN (
    if exist "%INSTALL_DIR%\.env" (
        for /f "usebackq tokens=1,* delims==" %%a in ("%INSTALL_DIR%\.env") do (
            if /i "%%a"=="MESHCTX_CORE_TOKEN" set "MESHCTX_CORE_TOKEN=%%~b"
        )
    )
)
if defined MESHCTX_CORE_TOKEN (
    where git >nul 2>nul && (
        set "CORE_TMP=%TEMP%\meshctx_core_%RANDOM%"
        git clone --depth 1 "https://!MESHCTX_CORE_TOKEN!@github.com/LucyAndLuna2023/meshctx-core.git" "!CORE_TMP!\core" >nul 2>nul && set "CORE_CLONE_OK=1"
        if not defined CORE_CLONE_OK (
            if defined MESHCTX_GIT_PROXY (
                git -c http.proxy="!MESHCTX_GIT_PROXY!" -c https.proxy="!MESHCTX_GIT_PROXY!" clone --depth 1 "https://!MESHCTX_CORE_TOKEN!@github.com/LucyAndLuna2023/meshctx-core.git" "!CORE_TMP!\core" >nul 2>nul && set "CORE_CLONE_OK=1"
            )
        )
        if defined CORE_CLONE_OK (
            for /r "!CORE_TMP!\core\src\core" %%f in (*.py) do if /i not "%%~nxf"=="__init__.py" copy /y "%%f" "%INSTALL_DIR%\src\core\" >nul 2>nul
            echo   [OK] %_T_CORE_OK%
        ) else (
            echo   [ERROR] %_T_CORE_FAIL%
            if exist "!CORE_TMP!" rmdir /s /q "!CORE_TMP!" 2>nul
            pause
            exit /b 1
        )
        if exist "!CORE_TMP!" rmdir /s /q "!CORE_TMP!" 2>nul
    ) else (
        echo   [ERROR] %_T_GIT_MISSING%
        echo   [HINT] %_T_HINT_SETUP%
        pause
        exit /b 1
    )
) else (
    echo   [ERROR] %_T_TOKEN_MISSING%
    echo   [HINT] %_T_HINT_TOKEN%
    pause
    exit /b 1
)
echo   OK

:done
echo.
echo   %_T_DONE%
echo     "%INSTALL_DIR%\meshctx.cmd" start
echo     %_T_WEBUI% http://localhost:3001/ui/setup
echo.
pause
