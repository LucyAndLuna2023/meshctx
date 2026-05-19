@echo off
REM ═══════════════════════════════════════════════════
REM meshctx Windows 安装 (Python版)
REM 从 meshctx.com 下载，无需 GitHub/代理
REM ═══════════════════════════════════════════════════
title meshctx Installer
setlocal enabledelayedexpansion

set "INSTALL_DIR=%USERPROFILE%\.meshctx"
set "SRC_URL=https://meshctx.com/dl/meshctx-src.tar.gz"
set "VERSION=2.29.3"

echo.
echo   meshctx v%VERSION% — AI Agent Platform
echo   ======================================
echo.

REM ── 检查 Python ──
echo [1/4] Checking Python...
where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo   ERROR: Python not found.
    echo   Please install Python 3.10+ from https://python.org
    echo   (Make sure to check "Add Python to PATH" during install)
    pause
    exit /b 1
)
for /f "tokens=2" %%i in ('python -c "import sys;print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2^>nul') do set PYVER=%%i
echo   Python %PYVER% ready

REM ── 下载源码包 ──
echo [2/4] Downloading source tarball...
set "TMPDIR=%TEMP%\meshctx_%RANDOM%"
mkdir "%TMPDIR%" 2>nul
set "TARBALL=%TMPDIR%\meshctx-src.tar.gz"

REM 优先使用 curl (Win10+ 自带)
where curl >nul 2>nul
if %ERRORLEVEL% EQU 0 (
    curl -fsSL --connect-timeout 30 -o "%TARBALL%" "%SRC_URL%"
) else (
    REM 备选: PowerShell
    powershell -Command "Invoke-WebRequest -Uri '%SRC_URL%' -OutFile '%TARBALL%' -TimeoutSec 30"
)

if not exist "%TARBALL%" (
    echo   ERROR: Download failed. Check internet connection.
    echo   If meshctx.com is unreachable, try manual install:
    echo   https://github.com/LucyAndLuna2023/meshctx
    rmdir /s /q "%TMPDIR%" 2>nul
    pause
    exit /b 1
)
echo   Downloaded successfully

REM ── 解压 ──
echo [3/4] Extracting...
if exist "%INSTALL_DIR%" rmdir /s /q "%INSTALL_DIR%"
mkdir "%INSTALL_DIR%"

REM 使用 PowerShell 解压 tar.gz
powershell -Command "tar -xzf '%TARBALL%' -C '%INSTALL_DIR%' --strip-components=1" 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo   ERROR: Extraction failed.
    echo   Make sure you have tar support (Win10 1803+)
    rmdir /s /q "%TMPDIR%" 2>nul
    pause
    exit /b 1
)
echo   Extracted to %INSTALL_DIR%

REM ── 安装依赖 ──
echo [4/4] Installing Python dependencies...
cd /d "%INSTALL_DIR%"

if not exist "venv" python -m venv venv
call venv\Scripts\activate.bat

pip install -q --upgrade pip 2>nul
pip install -q -r requirements.txt 2>nul || (
    pip install -q fastapi uvicorn pydantic numpy openai jinja2 httpx pyyaml aiofiles packaging 2>nul
)

REM ── 清理 ──
rmdir /s /q "%TMPDIR%" 2>nul

REM ── 创建快捷方式 ──
powershell -Command "$ws=New-Object -ComObject WScript.Shell; $s=$ws.CreateShortcut([Environment]::GetFolderPath('Desktop')+'\meshctx.lnk'); $s.TargetPath='%INSTALL_DIR%\start_webui.bat'; $s.WorkingDirectory='%INSTALL_DIR%'; $s.IconLocation='%INSTALL_DIR%\logo.ico'; $s.Save()" 2>nul

REM ── 创建启动脚本 ──
echo @echo off > "%INSTALL_DIR%\start_webui.bat"
echo cd /d "%INSTALL_DIR%" >> "%INSTALL_DIR%\start_webui.bat"
echo call venv\Scripts\activate.bat >> "%INSTALL_DIR%\start_webui.bat"
echo python -m src.cli start >> "%INSTALL_DIR%\start_webui.bat"
echo pause >> "%INSTALL_DIR%\start_webui.bat"

echo.
echo   ========================================
echo   Installation complete!
echo.
echo   Desktop shortcut created: meshctx.lnk
echo   Or run manually:
echo     %INSTALL_DIR%\venv\Scripts\python -m src.cli setup
echo     %INSTALL_DIR%\venv\Scripts\python -m src.cli start
echo.
echo   Documentation: https://meshctx.com
echo   ========================================
pause
