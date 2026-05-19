@echo off
REM ═══════════════════════════════════════════════════
REM meshctx Windows 快速安装 (Python版)
REM ═══════════════════════════════════════════════════
title meshctx Installer
echo.
echo   meshctx — AI Agent Platform
echo   ============================
echo.
echo   Requires: Python 3.10+ (https://python.org)
echo.

set "INSTALL_DIR=%USERPROFILE%\.meshctx"

echo [1/3] Cloning meshctx...
if exist "%INSTALL_DIR%" (
    echo   Updating existing install...
    cd /d "%INSTALL_DIR%" && git pull --ff-only 2>nul
) else (
    git clone --depth 1 https://github.com/LucyAndLuna2023/meshctx.git "%INSTALL_DIR%" 2>nul || (
        echo   Git clone failed. Install git: https://git-scm.com
        echo   Or manually download: https://github.com/LucyAndLuna2023/meshctx
        pause
        exit /b 1
    )
)

cd /d "%INSTALL_DIR%"

echo [2/3] Installing dependencies...
if not exist "venv" python -m venv venv
call venv\Scripts\activate.bat
pip install -q --upgrade pip 2>nul
pip install -q fastapi uvicorn pydantic numpy openai jinja2 httpx pyyaml aiofiles 2>nul

echo [3/3] Creating shortcut...
powershell -Command "$ws=New-Object -ComObject WScript.Shell; $s=$ws.CreateShortcut([Environment]::GetFolderPath('Desktop')+'\meshctx.lnk'); $s.TargetPath='%INSTALL_DIR%\install.bat'; $s.WorkingDirectory='%INSTALL_DIR%'; $s.Save()" 2>nul

echo.
echo   ========================================
echo   Installation complete!
echo.
echo   Run configuration wizard:
echo     %INSTALL_DIR%\venv\Scripts\python -m src.cli setup
echo.
echo   Or start Web UI directly:
echo     %INSTALL_DIR%\venv\Scripts\python -m src.cli start
echo.
echo   Config docs: https://meshctx.com/docs/config
echo   ========================================
pause
