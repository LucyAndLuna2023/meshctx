@echo off
REM meshctx Windows Installer v5 — from GitHub Releases
REM i18n: set MESHCTX_LANG=zh|en (default: en)
title meshctx Installer
setlocal enabledelayedexpansion

set "INSTALL_DIR=%USERPROFILE%\.meshctx"
set "VERSION=3.120.3"
set "SRC_URL=https://github.com/LucyAndLuna2023/meshctx/archive/refs/tags/v%VERSION%.tar.gz"
set "PORTABLE_URL=https://github.com/LucyAndLuna2023/meshctx/releases/download/v%VERSION%/meshctx-windows-cli.zip"

REM ── i18n ─────────────────────────────────────────────
if "%MESHCTX_LANG%"=="" set "MESHCTX_LANG=en"
set "_T_STEP_CHECK=Checking Python..."
set "_T_STEP_DOWNLOAD=Downloading..."
set "_T_STEP_EXTRACT=Extracting..."
set "_T_STEP_DEPS=Installing dependencies..."
set "_T_PYTHON_MISSING=Install Python 3.10+ from python.org"
set "_T_DOWNLOAD_FAIL=FAILED. Check network, or use WSL"
set "_T_EXTRACT_FAIL=FAILED (need Win10 1803+)"
set "_T_DONE=Done! Run:"
if /i "%MESHCTX_LANG%"=="zh" (
    set "_T_STEP_CHECK=检查 Python..."
    set "_T_STEP_DOWNLOAD=下载..."
    set "_T_STEP_EXTRACT=解压..."
    set "_T_STEP_DEPS=安装依赖..."
    set "_T_PYTHON_MISSING=请从 python.org 安装 Python 3.10+"
    set "_T_DOWNLOAD_FAIL=下载失败。请检查网络，或使用 WSL"
    set "_T_EXTRACT_FAIL=解压失败 (需要 Win10 1803+)"
    set "_T_DONE=安装完成！运行："
)

echo.
echo   meshctx v%VERSION%
echo   ================
echo.

set "TMPDIR=%TEMP%\meshctx_%RANDOM%"
mkdir "%TMPDIR%" 2>nul

REM ── [1/4] 完整版封装资产优先（护城河: 含闭源核心, 免 Python）──
set "PORTABLE_OK="
set "PORTABLE_TARBALL=%TMPDIR%\meshctx-windows-cli.zip"
echo [1/4] Downloading full portable build (closed-source core included)...
curl -fsSL --connect-timeout 60 --max-time 900 -o "%PORTABLE_TARBALL%" "%PORTABLE_URL%" 2>nul
if exist "%PORTABLE_TARBALL%" (
    tar -tf "%PORTABLE_TARBALL%" >nul 2>nul
    if not errorlevel 1 set "PORTABLE_OK=1"
)
if defined PORTABLE_OK (
    echo   [OK] Full portable asset (no Python needed)
) else (
    echo   [WARN] Portable asset unavailable, fallback to source install...
)

REM ── [2/4] 安装 ───────────────────────────────────────
if defined PORTABLE_OK (
    echo [2/4] Extracting portable...
    if exist "%INSTALL_DIR%" rmdir /s /q "%INSTALL_DIR%"
    mkdir "%INSTALL_DIR%"
    powershell -Command "tar -xf '%PORTABLE_TARBALL%' -C '%INSTALL_DIR%'" 2>nul || (
        echo   %_T_EXTRACT_FAIL%
        rmdir /s /q "%TMPDIR%" 2>nul
        pause
        exit /b 1
    )
    if not exist "%INSTALL_DIR%\meshctx\meshctx.exe" (
        echo   [ERROR] meshctx.exe missing in portable asset
        rmdir /s /q "%TMPDIR%" 2>nul
        pause
        exit /b 1
    )
    REM 命令行 wrapper
    > "%INSTALL_DIR%\meshctx.cmd" echo @echo off
    >> "%INSTALL_DIR%\meshctx.cmd" echo "%%~dp0meshctx\meshctx.exe" %%*
    rmdir /s /q "%TMPDIR%" 2>nul
    echo   [OK] Closed-source core embedded (full portable build, no Python needed)
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
echo [5/5] Installing closed-source core meshctx-core ...
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
            echo   [OK] Closed-source core installed as one product (full build)
        ) else (
            echo   [ERROR] Failed to fetch closed-source core (token/network) — full product must include the core, stub install forbidden
            if exist "!CORE_TMP!" rmdir /s /q "!CORE_TMP!" 2>nul
            pause
            exit /b 1
        )
        if exist "!CORE_TMP!" rmdir /s /q "!CORE_TMP!" 2>nul
    ) else (
        echo   [ERROR] git not installed — source install mode needs git + MESHCTX_CORE_TOKEN for the closed-source core
        echo   [HINT] Use the official installer meshctx-setup.exe (includes closed-source core), or install git, set MESHCTX_CORE_TOKEN and re-run
        pause
        exit /b 1
    )
) else (
    echo   [ERROR] MESHCTX_CORE_TOKEN not provided — full product must include the closed-source core, stub install forbidden
    echo   [HINT] Use the official installer meshctx-setup.exe (includes closed-source core), or set MESHCTX_CORE_TOKEN and re-run
    pause
    exit /b 1
)
echo   OK

:done
echo.
echo   %_T_DONE%
echo     "%INSTALL_DIR%\meshctx.cmd" start    (full portable build / or venv source)
echo     Web UI: http://localhost:3001/ui/setup
echo.
pause
