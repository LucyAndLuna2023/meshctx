@echo off
REM meshctx Windows 安装 v5 — 从 GitHub Releases 下载
title meshctx Installer
setlocal enabledelayedexpansion

set "INSTALL_DIR=%USERPROFILE%\.meshctx"
set "VERSION=2.29.3"
set "SRC_URL=https://github.com/LucyAndLuna2023/meshctx/releases/download/v%VERSION%/meshctx-src.tar.gz"

echo.
echo   meshctx v%VERSION%
echo   ================
echo.

echo [1/4] Python...
where python >nul 2>nul || (echo   Install Python 3.10+ from python.org && pause && exit /b 1)
echo   OK

echo [2/4] Downloading...
set "TMPDIR=%TEMP%\meshctx_%RANDOM%"
mkdir "%TMPDIR%" 2>nul
curl -fsSL --connect-timeout 60 -o "%TMPDIR%\meshctx-src.tar.gz" "%SRC_URL%" 2>nul || (
    echo   FAILED. Manual: git clone https://github.com/LucyAndLuna2023/meshctx %%USERPROFILE%%\.meshctx
    rmdir /s /q "%TMPDIR%" 2>nul
    pause
    exit /b 1
)
echo   OK

echo [3/4] Extracting...
if exist "%INSTALL_DIR%" rmdir /s /q "%INSTALL_DIR%"
mkdir "%INSTALL_DIR%"
powershell -Command "tar -xzf '%TMPDIR%\meshctx-src.tar.gz' -C '%INSTALL_DIR%' --strip-components=1" 2>nul || (
    echo   FAILED (need Win10 1803+)
    rmdir /s /q "%TMPDIR%" 2>nul
    pause
    exit /b 1
)
rmdir /s /q "%TMPDIR%" 2>nul
echo   OK

echo [4/4] Dependencies...
cd /d "%INSTALL_DIR%"
if not exist "venv" python -m venv venv
call venv\Scripts\activate.bat
pip install -q fastapi uvicorn pydantic numpy openai jinja2 httpx pyyaml aiofiles packaging 2>nul
echo   OK

echo.
echo   Done! Run:
echo     %INSTALL_DIR%\venv\Scripts\python -m src.cli setup
echo     %INSTALL_DIR%\venv\Scripts\python -m src.cli start
pause
