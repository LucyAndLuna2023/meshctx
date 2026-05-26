@echo off
REM MeshCtx v3.33 Windows 构建脚本
REM 需要: Python 3.10+, PyInstaller, NSIS
echo ============================================
echo  MeshCtx v3.33 Windows Desktop Build
echo ============================================
echo.

REM 1. 安装依赖
echo [1/4] Installing Python dependencies...
pip install -r requirements.txt --quiet

REM 2. PyInstaller 打包
echo [2/4] Building with PyInstaller...
pyinstaller meshctx_desktop.spec --clean --noconfirm
if errorlevel 1 (
    echo ERROR: PyInstaller build failed!
    exit /b 1
)

REM 3. NSIS 安装包
echo [3/4] Creating NSIS installer...
makensis meshctx_setup.nsi
if errorlevel 1 (
    echo ERROR: NSIS build failed!
    exit /b 1
)

REM 4. 验证
echo [4/4] Verifying build...
if exist "dist\meshctx-setup.exe" (
    echo     meshctx-setup.exe 构建成功
    echo.
    echo ============================================
    echo  BUILD SUCCESS!
    echo  Output: dist\meshctx-setup.exe
    echo  Version: v3.33.0
    echo ============================================
) else (
    echo ERROR: meshctx-setup.exe not found!
    exit /b 1
)