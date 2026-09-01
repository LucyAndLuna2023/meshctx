@echo off
chcp 65001 >nul
REM ═══════════════════════════════════════════════════════
REM meshctx Edition Installer — Personal / Team / Enterprise
REM Usage:
REM   personal:   install-edition.bat personal
REM   team:       install-edition.bat team
REM   enterprise: install-edition.bat enterprise
REM Requires: MESHCTX_GIT_TOKEN env for team/enterprise
REM ═══════════════════════════════════════════════════════
setlocal enabledelayedexpansion
title meshctx Edition Installer

set "EDITION=%~1"
if "%EDITION%"=="" set "EDITION=personal"
set "VERSION=3.121.7"
set "INSTALL_DIR=%USERPROFILE%\.meshctx"

if "%EDITION%"=="personal" (
  set "LABEL=Personal (free)"
) else if "%EDITION%"=="team" (
  set "LABEL=Team ($9/人/月)"
) else if "%EDITION%"=="enterprise" (
  set "LABEL=Enterprise ($29/人/月)"
) else (
  echo Unknown edition: %EDITION% (use personal^|team^|enterprise)
  exit /b 1
)

echo ============================================
echo  meshctx %LABEL% Installer v%VERSION%
echo ============================================

mkdir "%INSTALL_DIR%\src" 2>nul

echo [1/3] Downloading meshctx base...
git clone --depth 1 --branch v%VERSION% https://github.com/LucyAndLuna2023/meshctx.git "%INSTALL_DIR%\src\meshctx" 2>nul
if errorlevel 1 (
  git clone --depth 1 https://github.com/LucyAndLuna2023/meshctx.git "%INSTALL_DIR%\src\meshctx" 2>nul
)

if not "%EDITION%"=="personal" (
  if "%MESHCTX_GIT_TOKEN%"=="" (
    echo [ERROR] Team/Enterprise need MESHCTX_GIT_TOKEN ^(GitHub token^)
    echo Get: https://github.com/settings/tokens
    exit /b 1
  )
  echo [2/3] Downloading private repos...
  if "%EDITION%"=="team" (
    git clone --depth 1 https://%MESHCTX_GIT_TOKEN%@github.com/LucyAndLuna2023/meshctx-team.git "%INSTALL_DIR%\src\meshctx-team" 2>nul
    git -C "%INSTALL_DIR%\src\meshctx-team" remote set-url origin https://github.com/LucyAndLuna2023/meshctx-team.git 2>nul
  ) else (
    git clone --depth 1 https://%MESHCTX_GIT_TOKEN%@github.com/LucyAndLuna2023/meshctx-team.git "%INSTALL_DIR%\src\meshctx-team" 2>nul
    git clone --depth 1 https://%MESHCTX_GIT_TOKEN%@github.com/LucyAndLuna2023/meshctx-enterprise.git "%INSTALL_DIR%\src\meshctx-enterprise" 2>nul
    git -C "%INSTALL_DIR%\src\meshctx-team" remote set-url origin https://github.com/LucyAndLuna2023/meshctx-team.git 2>nul
    git -C "%INSTALL_DIR%\src\meshctx-enterprise" remote set-url origin https://github.com/LucyAndLuna2023/meshctx-enterprise.git 2>nul
  )
  echo [3/3] Merging private modules...
  copy /y "%INSTALL_DIR%\src\meshctx-team\src\core\*.py" "%INSTALL_DIR%\src\meshctx\src\core\" >nul 2>nul
  copy /y "%INSTALL_DIR%\src\meshctx-team\src\web_crews.py" "%INSTALL_DIR%\src\meshctx\src\" >nul 2>nul
  if "%EDITION%"=="enterprise" (
    copy /y "%INSTALL_DIR%\src\meshctx-enterprise\src\core\*.py" "%INSTALL_DIR%\src\meshctx\src\core\" >nul 2>nul
    copy /y "%INSTALL_DIR%\src\meshctx-enterprise\src\web_crews.py" "%INSTALL_DIR%\src\meshctx\src\" >nul 2>nul
  )
)

echo.
echo  ============================================
echo   DONE: meshctx %LABEL% v%VERSION%
echo   Run: cd %INSTALL_DIR%\src\meshctx ^&^& python -m uvicorn src.main:app --port 3001
echo  ============================================
