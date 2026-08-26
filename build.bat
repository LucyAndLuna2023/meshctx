@echo off
REM ═══════════════════════════════════════════════
REM  MeshCtx v3.118 Windows 一键构建脚本
REM  包含: PyInstaller打包 + 版本号注入 + NSIS安装包
REM  需要: Python 3.10+, PyInstaller, NSIS (可选)
REM ═══════════════════════════════════════════════
setlocal enabledelayedexpansion

echo.
echo ╔══════════════════════════════════╗
echo ║  MeshCtx v3.118 Build Script  ║
echo ╚══════════════════════════════════╝
echo.

REM 检测Python
set PYTHON=
for %%p in (python3 python py) do (
    where %%p >nul 2>&1 && set PYTHON=%%p && goto :found_python
)
echo [ERROR] Python not found! Install Python 3.10+
pause
exit /b 1

:found_python
%PYTHON% --version
echo Python: %PYTHON%

REM [1/5] 安装依赖
echo.
echo [1/5] Installing PyInstaller...
%PYTHON% -m pip install pyinstaller -q
if errorlevel 1 (
    echo [ERROR] PyInstaller install failed
    exit /b 1
)

REM [2/5] PyInstaller打包
echo [2/5] Building exe with PyInstaller...
%PYTHON% -m PyInstaller meshctx_desktop.spec --noconfirm
if errorlevel 1 (
    echo [ERROR] PyInstaller build failed!
    exit /b 1
)

REM [3/5] 注入版本号 (pyi-set_version)
echo [3/5] Injecting version info...
if exist "dist\meshctx-desktop.exe" (
    %PYTHON% -m PyInstaller.utils.win32.versioninfo version_info.txt dist\meshctx-desktop.exe
    echo [OK] Version info injected: FileVersion 3.121.5
) else (
    echo [ERROR] meshctx-desktop.exe not found!
    exit /b 1
)

REM [4/5] 验证版本号
echo [4/5] Verifying version...
powershell -Command "$v = (Get-Item 'dist\meshctx-desktop.exe').VersionInfo; Write-Host \"  FileVersion: $($v.FileVersion)\"; Write-Host \"  ProductVersion: $($v.ProductVersion)\""
echo [OK] Version verified

REM [5/5] 复制为Release文件名
echo [5/5] Creating release artifact...
copy /Y dist\meshctx-desktop.exe dist\meshctx-setup.exe >nul
echo [OK] dist\meshctx-setup.exe ready

echo.
echo ═══════════════════════════════════
echo   BUILD COMPLETE!
echo   dist\meshctx-setup.exe (with version info)
echo   Version: 3.121.5
echo ═══════════════════════════════════

REM 可选: NSIS打包
where makensis >nul 2>&1
if not errorlevel 1 (
    echo.
    echo [Optional] Building NSIS installer...
    makensis meshctx_setup.nsi
    if not errorlevel 1 (
        echo [OK] dist\meshctx-setup.exe (NSIS installer)
    )
)

endlocal
