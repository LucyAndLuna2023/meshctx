@echo off
chcp 65001 >nul
REM meshctx Windows Installer v5 — from GitHub Releases
REM i18n: set MESHCTX_LANG=zh|en|ja|ko|fr|de|es|it|ar (default: en)
title meshctx Installer
setlocal enabledelayedexpansion

set "INSTALL_DIR=%USERPROFILE%\.meshctx"
set "VERSION=3.121.3"
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
set "_T_CORE_FAIL=Closed-source core fetch failed - continuing with open-source build (full engine). Core is optional; re-run with MESHCTX_CORE_TOKEN to add it later"
set "_T_GIT_MISSING=git not installed - open-source build installs fine. Closed-source core is optional"
set "_T_HINT_SETUP=Set MESHCTX_CORE_TOKEN and re-run to add the optional core enhancement layer"
set "_T_TOKEN_MISSING=No MESHCTX_CORE_TOKEN - installing open-source build (full engine, Open Core)"
set "_T_HINT_TOKEN=Core is optional; set MESHCTX_CORE_TOKEN and re-run to add it later"
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
    set "_T_CORE_FAIL=闭源核心获取失败 - 继续安装开源版（完整引擎）。核心为可选增强层，设置 MESHCTX_CORE_TOKEN 后可补装"
    set "_T_GIT_MISSING=未安装 git - 开源版可正常安装。闭源核心为可选增强层"
    set "_T_HINT_SETUP=设置 MESHCTX_CORE_TOKEN 后重跑可补装可选核心增强层"
    set "_T_TOKEN_MISSING=未设置 MESHCTX_CORE_TOKEN - 安装开源版（完整引擎，Open Core）"
    set "_T_HINT_TOKEN=核心为可选；设置 MESHCTX_CORE_TOKEN 后重跑即可补装"
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
    set "_T_CORE_FAIL=クローズドソースコアの取得に失敗 - オープンソース版（フルエンジン）で続行。コアは任意の拡張レイヤー。MESHCTX_CORE_TOKEN 設定後に再実行で補完可能"
    set "_T_GIT_MISSING=git 未インストール - オープンソース版は正常にインストール可能。クローズドソースコアは任意"
    set "_T_HINT_SETUP=MESHCTX_CORE_TOKEN を設定して再実行すると任意のコア拡張レイヤーを補完できます"
    set "_T_TOKEN_MISSING=MESHCTX_CORE_TOKEN 未設定 - オープンソース版（フルエンジン、Open Core）をインストール"
    set "_T_HINT_TOKEN=コアは任意です。MESHCTX_CORE_TOKEN を設定して再実行で補完可能"
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
    set "_T_CORE_FAIL=클로즈드 소스 코어 가져오기 실패 - 오픈소스 버전(전체 엔진)으로 계속 설치합니다. 코어는 선택적 확장 계층이며 MESHCTX_CORE_TOKEN 설정 후 재실행으로 추가 가능"
    set "_T_GIT_MISSING=git 미설치 - 오픈소스 버전은 정상 설치 가능. 클로즈드 소스 코어는 선택 사항"
    set "_T_HINT_SETUP=MESHCTX_CORE_TOKEN 설정 후 재실행하면 선택적 코어 확장 계층을 추가할 수 있습니다"
    set "_T_TOKEN_MISSING=MESHCTX_CORE_TOKEN 미설정 - 오픈소스 버전(전체 엔진, Open Core) 설치"
    set "_T_HINT_TOKEN=코어는 선택 사항입니다. MESHCTX_CORE_TOKEN 설정 후 재실행으로 추가 가능"
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
    set "_T_CORE_FAIL=Echec de recuperation du noyau closed-source - poursuite avec la version open-source (moteur complet). Le noyau est une couche optionnelle ; relancez avec MESHCTX_CORE_TOKEN pour l ajouter"
    set "_T_GIT_MISSING=git non installe - la version open-source s installe normalement. Le noyau closed-source est optionnel"
    set "_T_HINT_SETUP=Definissez MESHCTX_CORE_TOKEN et relancez pour ajouter la couche de noyau optionnelle"
    set "_T_TOKEN_MISSING=MESHCTX_CORE_TOKEN non fourni - installation de la version open-source (moteur complet, Open Core)"
    set "_T_HINT_TOKEN=Le noyau est optionnel ; definissez MESHCTX_CORE_TOKEN et relancez pour l ajouter"
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
    set "_T_CORE_FAIL=Abruf des Closed-Source-Kerns fehlgeschlagen - Fortsetzung mit Open-Source-Build (voller Kernel). Der Kern ist eine optionale Schicht; mit MESHCTX_CORE_TOKEN erneut ausfuehren"
    set "_T_GIT_MISSING=git nicht installiert - Open-Source-Build installiert normal. Closed-Source-Kern ist optional"
    set "_T_HINT_SETUP=MESHCTX_CORE_TOKEN setzen und erneut ausfuehren, um die optionale Kernschicht hinzuzufuegen"
    set "_T_TOKEN_MISSING=MESHCTX_CORE_TOKEN fehlt - Installation des Open-Source-Builds (voller Kernel, Open Core)"
    set "_T_HINT_TOKEN=Der Kern ist optional; MESHCTX_CORE_TOKEN setzen und erneut ausfuehren"
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
    set "_T_CORE_FAIL=Error al obtener el nucleo de codigo cerrado - se continua con la version open-source (motor completo). El nucleo es una capa opcional; ejecute de nuevo con MESHCTX_CORE_TOKEN"
    set "_T_GIT_MISSING=git no instalado - la version open-source se instala correctamente. El nucleo de codigo cerrado es opcional"
    set "_T_HINT_SETUP=Configure MESHCTX_CORE_TOKEN y vuelva a ejecutar para anadir la capa de nucleo opcional"
    set "_T_TOKEN_MISSING=MESHCTX_CORE_TOKEN no proporcionado - instalando version open-source (motor completo, Open Core)"
    set "_T_HINT_TOKEN=El nucleo es opcional; configure MESHCTX_CORE_TOKEN y vuelva a ejecutar"
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
    set "_T_CORE_FAIL=Recupero del core closed-source fallito - si continua con la build open-source (motore completo). Il core e un livello opzionale; rieseguire con MESHCTX_CORE_TOKEN"
    set "_T_GIT_MISSING=git non installato - la build open-source si installa normalmente. Il core closed-source e opzionale"
    set "_T_HINT_SETUP=Impostare MESHCTX_CORE_TOKEN e rieseguire per aggiungere il livello core opzionale"
    set "_T_TOKEN_MISSING=MESHCTX_CORE_TOKEN non fornito - installazione build open-source (motore completo, Open Core)"
    set "_T_HINT_TOKEN=Il core e opzionale; impostare MESHCTX_CORE_TOKEN e rieseguire per aggiungerlo"
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
    set "_T_CORE_FAIL=فشل الحصول على النواة مغلقة المصدر - المتابعة مع الإصدار مفتوح المصدر (المحرك الكامل). النواة طبقة اختيارية؛ أعد التشغيل مع MESHCTX_CORE_TOKEN لإضافتها لاحقا"
    set "_T_GIT_MISSING=git غير مثبت - الإصدار مفتوح المصدر يثبت بشكل طبيعي. النواة مغلقة المصدر اختيارية"
    set "_T_HINT_SETUP=اضبط MESHCTX_CORE_TOKEN وأعد التشغيل لإضافة طبقة النواة الاختيارية"
    set "_T_TOKEN_MISSING=لم يتم توفير MESHCTX_CORE_TOKEN - تثبيت الإصدار مفتوح المصدر (المحرك الكامل، Open Core)"
    set "_T_HINT_TOKEN=النواة اختيارية؛ اضبط MESHCTX_CORE_TOKEN وأعد التشغيل لإضافتها"
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
            echo   [WARN] %_T_CORE_FAIL%
            if exist "!CORE_TMP!" rmdir /s /q "!CORE_TMP!" 2>nul
        )
        if exist "!CORE_TMP!" rmdir /s /q "!CORE_TMP!" 2>nul
    ) else (
        echo   [WARN] %_T_GIT_MISSING%
        echo   [HINT] %_T_HINT_SETUP%
    )
) else (
    echo   [INFO] %_T_TOKEN_MISSING%
    echo   [HINT] %_T_HINT_TOKEN%
)
echo   OK

:done
echo.
echo   %_T_DONE%
echo     "%INSTALL_DIR%\meshctx.cmd" start
echo     %_T_WEBUI% http://localhost:3001/ui/setup
echo.
pause
