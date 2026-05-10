@echo off
echo ╔═══════════════════════════════════════════╗
echo ║     meshctx v1.0  Windows 一键安装       ║
echo ║   World's First Self-Evolving Agent      ║
echo ╚═══════════════════════════════════════════╝
echo.

REM 检查 WSL
wsl --status >nul 2>&1
if %errorlevel% neq 0 (
    echo 需要先安装 WSL (Windows Subsystem for Linux)
    echo 以管理员身份运行: wsl --install
    pause
    exit /b 1
)

echo [1/4] 检查 WSL 环境...
wsl echo "WSL OK" >nul 2>&1
if %errorlevel% neq 0 (
    echo WSL 未正确配置，请先运行: wsl --install
    pause
    exit /b 1
)

echo [2/4] 下载 meshctx...
wsl bash -c "curl -fsSL https://raw.githubusercontent.com/LucyAndLuna2023/meshctx/main/install.sh | bash"

echo [3/4] 配置完成!

echo [4/4] 打开 Web Chat...
start http://localhost:3000/ui/chat
start http://localhost:3000/ui/setup

echo.
echo ╔═══════════════════════════════════════════╗
echo ║       meshctx 安装完成!                  ║
echo ║  Web Chat: http://localhost:3000/ui/chat ║
echo ║  设置向导: http://localhost:3000/ui/setup║
echo ╚═══════════════════════════════════════════╝
echo.
echo 在 WSL 终端中运行: meshctx chat
pause
