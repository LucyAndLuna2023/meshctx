@echo off
title meshctx v1.1 — AI Agent Installer
echo.
echo   meshctx v1.1 — World's First Self-Evolving Agent
echo   ================================================
echo.

:: === 下载预构建包 ===
set "MESHCTX_DIR=%USERPROFILE%\.meshctx"
set "PACKAGE_URL=https://github.com/LucyAndLuna2023/meshctx/releases/latest/download"

echo [1/3] Downloading meshctx package...
if not exist "%MESHCTX_DIR%" mkdir "%MESHCTX_DIR%"

:: 下载嵌入式Python + meshctx 预构建包
powershell -Command "Invoke-WebRequest -Uri '%PACKAGE_URL%/meshctx-windows.zip' -OutFile '%TEMP%\meshctx.zip'" 2>nul
if %errorlevel% neq 0 (
    echo   GitHub下载失败，尝试备用源...
    powershell -Command "Invoke-WebRequest -Uri 'https://meshctx.com/dl/meshctx-windows.zip' -OutFile '%TEMP%\meshctx.zip'" 2>nul
)

if exist "%TEMP%\meshctx.zip" (
    echo [2/3] Extracting...
    powershell -Command "Expand-Archive -Force '%TEMP%\meshctx.zip' '%MESHCTX_DIR%'"
    del "%TEMP%\meshctx.zip"
) else (
    echo   Download failed. Please visit:
    echo   https://github.com/LucyAndLuna2023/meshctx
    pause
    exit /b 1
)

:: === 配置 API Key ===
echo [3/3] Setting up...
cd /d "%MESHCTX_DIR%"

:: 交互式输入 Key
set /p API_KEY="Enter your DeepSeek API Key (free at platform.deepseek.com): "
if not "%API_KEY%"=="" (
    setx DEEPSEEK_API_KEY "%API_KEY%" >nul
    echo DEEPSEEK_API_KEY=%API_KEY%> .env
)

:: === 创建桌面快捷方式 ===
powershell -Command "$ws=New-Object -ComObject WScript.Shell; $s=$ws.CreateShortcut([Environment]::GetFolderPath('Desktop')+'\meshctx.lnk'); $s.TargetPath='%MESHCTX_DIR%\meshctx.exe'; $s.WorkingDirectory='%MESHCTX_DIR%'; $s.Save()" 2>nul

:: === 启动 ===
echo.
echo   Installation complete!
echo   Starting meshctx...
start "" "%MESHCTX_DIR%\meshctx.exe" start
start http://localhost:3000/ui/chat

echo   Web Chat: http://localhost:3000/ui/chat
echo   Enter /gateway in chat to connect WeChat/Feishu/Telegram
pause
