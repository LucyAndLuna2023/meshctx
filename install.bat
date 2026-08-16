@echo off
REM meshctx Windows Installer v5 — from GitHub Releases
REM i18n: set MESHCTX_LANG=zh|en (default: en)
title meshctx Installer
setlocal enabledelayedexpansion

set "INSTALL_DIR=%USERPROFILE%\.meshctx"
set "VERSION=3.118.0"
set "SRC_URL=https://github.com/LucyAndLuna2023/meshctx/archive/refs/tags/v%VERSION%.tar.gz"

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

echo [1/4] %_T_STEP_CHECK%
where python >nul 2>nul || (echo   %_T_PYTHON_MISSING% && pause && exit /b 1)
echo   OK

echo [2/4] %_T_STEP_DOWNLOAD%
set "TMPDIR=%TEMP%\meshctx_%RANDOM%"
mkdir "%TMPDIR%" 2>nul
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
echo [5/5] 安装闭源核心 meshctx-core ...
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
            echo   [OK] 闭源核心已一体安装（完整版）
        ) else (
            echo   [WARN] 闭源核心拉取失败（token/网络），本次为开源 stub 模式
        )
        if exist "!CORE_TMP!" rmdir /s /q "!CORE_TMP!" 2>nul
    )
)
echo   OK

echo.
echo   %_T_DONE%
echo     %INSTALL_DIR%\venv\Scripts\python -m src.cli setup
echo     %INSTALL_DIR%\venv\Scripts\python -m src.cli start
pause
