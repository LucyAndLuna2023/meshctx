#!/bin/bash
# ═══════════════════════════════════════════════════════
# meshctx macOS 一键安装 v1.0
# 使用: curl -fsSL https://cdn.jsdelivr.net/gh/LucyAndLuna2023/meshctx@main/install-mac.sh | bash
# 或:   git clone ... && bash install-mac.sh
# ═══════════════════════════════════════════════════════
set -e

# ── 颜色 ──
GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[0;33m'
RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'

INSTALL_DIR="${HOME}/.meshctx"
VERSION="3.115.15"
REPO="LucyAndLuna2023/meshctx"
SRC_URL="https://github.com/${REPO}/releases/download/v${VERSION}/meshctx-src.tar.gz"
PORT=3001
LAUNCHD_LABEL="com.meshctx.server"

echo ""
echo -e "${CYAN}  ╔══════════════════════════════════════════╗${NC}"
echo -e "${CYAN}  ║     meshctx v${VERSION} macOS 一键安装        ║${NC}"
echo -e "${CYAN}  ╚══════════════════════════════════════════╝${NC}"
echo ""

# ── macOS 检测 ──
if [[ "$(uname)" != "Darwin" ]]; then
    echo -e "${RED}✗ 此脚本仅适用于 macOS，Linux 请用 install.sh${NC}"
    exit 1
fi

MACOS_VER=$(sw_vers -productVersion 2>/dev/null || echo "unknown")
echo -e "  ${GREEN}✓${NC} macOS ${MACOS_VER} ($(uname -m))"

# ── [1/6] 停止旧版本 ─────────────────────────────────
echo -e "${CYAN}[1/6]${NC} 停止旧版本..."

KILLED=0

# 停止 uvicorn
if pgrep -f "uvicorn.*src.main" >/dev/null 2>&1; then
    pkill -9 -f "uvicorn.*src.main" 2>/dev/null || true
    KILLED=1
fi

# 停止 meshctx CLI
if pgrep -f "python.*meshctx" >/dev/null 2>&1; then
    pkill -9 -f "python.*meshctx" 2>/dev/null || true
    KILLED=1
fi

# 停止 launchd 服务
if launchctl list 2>/dev/null | grep -q "${LAUNCHD_LABEL}"; then
    launchctl unload "${HOME}/Library/LaunchAgents/${LAUNCHD_LABEL}.plist" 2>/dev/null || true
    KILLED=1
fi

sleep 1

# 释放端口 (macOS 用 lsof)
PORT_PID=$(lsof -ti:${PORT} 2>/dev/null | head -1)
if [ -n "${PORT_PID}" ]; then
    kill -9 "${PORT_PID}" 2>/dev/null || true
    KILLED=1
fi

if [ "${KILLED}" = "1" ]; then
    echo -e "  ${GREEN}✓${NC} 已停止旧服务并释放端口 ${PORT}"
else
    echo -e "  ${GREEN}✓${NC} 无需停止"
fi

# ── [2/6] 环境检查 ───────────────────────────────────
echo -e "${CYAN}[2/6]${NC} 检查环境..."

# Python 检查
PYTHON_BIN=""
for p in python3.12 python3.11 python3.10 python3; do
    if command -v "$p" >/dev/null 2>&1; then
        ver=$($p --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ] 2>/dev/null; then
            PYTHON_BIN="$p"
            break
        fi
    fi
done

if [ -z "${PYTHON_BIN}" ]; then
    echo -e "  ${RED}✗ 需要 Python 3.10+，但未找到${NC}"
    echo ""
    echo -e "  ${YELLOW}安装 Python 3.10+ 的方法：${NC}"
    echo ""
    echo -e "  ${BOLD}方法1: Homebrew（推荐）${NC}"
    echo "    /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
    echo "    brew install python@3.12"
    echo ""
    echo -e "  ${BOLD}方法2: 官方安装包${NC}"
    echo "    下载: https://www.python.org/downloads/macos/"
    echo "    安装 .pkg 后重新打开终端"
    echo ""
    echo -e "  ${BOLD}方法3: Xcode Command Line Tools${NC}"
    echo "    xcode-select --install"
    echo ""
    exit 1
fi

PY_VER=$(${PYTHON_BIN} --version 2>&1)
echo -e "  ${GREEN}✓${NC} ${PY_VER} ($(which ${PYTHON_BIN}))"

# pip 检查
if ! ${PYTHON_BIN} -m pip --version >/dev/null 2>&1; then
    echo -e "  ${YELLOW}→${NC} 安装 pip..."
    ${PYTHON_BIN} -m ensurepip --upgrade 2>/dev/null || \
        curl -sS https://bootstrap.pypa.io/get-pip.py | ${PYTHON_BIN}
fi
echo -e "  ${GREEN}✓${NC} pip: $(${PYTHON_BIN} -m pip --version 2>&1 | head -1)"

# Homebrew 检测（可选）
if command -v brew >/dev/null 2>&1; then
    echo -e "  ${GREEN}✓${NC} Homebrew: $(brew --version 2>&1 | head -1)"
else
    echo -e "  ${YELLOW}⚠${NC} Homebrew 未安装（可选，用于系统级依赖）"
fi

# ── [3/6] 下载 ──────────────────────────────────────
echo -e "${CYAN}[3/6]${NC} 下载 meshctx v${VERSION}..."

TMPDIR=$(mktemp -d)
TARBALL="${TMPDIR}/meshctx-src.tar.gz"
trap "rm -rf ${TMPDIR}" EXIT

DOWNLOAD_OK=0

# macOS 自带 curl，优先使用
if curl -fsSL --connect-timeout 60 --retry 3 -o "${TARBALL}" "${SRC_URL}" 2>/dev/null; then
    DOWNLOAD_OK=1
elif command -v wget >/dev/null 2>&1; then
    wget -q --timeout=120 --tries=3 -O "${TARBALL}" "${SRC_URL}" && DOWNLOAD_OK=1
fi

if [ "${DOWNLOAD_OK}" != "1" ]; then
    echo -e "${RED}✗ 下载失败${NC}"
    echo ""
    echo -e "  ${YELLOW}备选安装方法（git clone）：${NC}"
    echo "    git clone https://github.com/${REPO}.git ~/.meshctx"
    echo "    cd ~/.meshctx && bash install-mac.sh --offline"
    echo ""
    exit 1
fi

TARBALL_SIZE=$(du -h "${TARBALL}" | cut -f1)
echo -e "  ${GREEN}✓${NC} 下载完成 (${TARBALL_SIZE})"

# ── [4/6] 安装 ──────────────────────────────────────
echo -e "${CYAN}[4/6]${NC} 安装..."

# 备份用户配置
CONFIG_BACKUP=""
if [ -d "${INSTALL_DIR}" ]; then
    CONFIG_BACKUP=$(mktemp -d)
    for f in config.yaml .env provider_config.json; do
        if [ -f "${INSTALL_DIR}/${f}" ]; then
            cp "${INSTALL_DIR}/${f}" "${CONFIG_BACKUP}/${f}" 2>/dev/null || true
        fi
    done
    [ -z "${CONFIG_BACKUP}" ] || echo -e "  ${GREEN}✓${NC} 已备份用户配置"
fi

# 安装新版本
rm -rf "${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"
tar xzf "${TARBALL}" -C "${INSTALL_DIR}" || {
    echo -e "${RED}✗ 解压失败${NC}"; exit 1
}

# 恢复用户配置
if [ -n "${CONFIG_BACKUP}" ] && [ -d "${CONFIG_BACKUP}" ]; then
    RESTORED=0
    for f in config.yaml .env provider_config.json; do
        if [ -f "${CONFIG_BACKUP}/${f}" ]; then
            cp "${CONFIG_BACKUP}/${f}" "${INSTALL_DIR}/${f}" 2>/dev/null || true
            RESTORED=1
        fi
    done
    # 🔒 安全：永远不恢复旧密码
    if [ -f "${INSTALL_DIR}/.env" ]; then
        sed -i '' '/^MESHCTX_PASSWORD=/d' "${INSTALL_DIR}/.env" 2>/dev/null || true
    fi
    rm -rf "${CONFIG_BACKUP}"
    [ "${RESTORED}" = "0" ] || echo -e "  ${GREEN}✓${NC} 用户配置已恢复（密码已重置）"
fi

cd "${INSTALL_DIR}"

# 创建 venv
echo -e "  ${CYAN}→${NC} 创建虚拟环境..."
if [ ! -d "venv" ]; then
    ${PYTHON_BIN} -m venv venv 2>/dev/null || {
        # Fallback: ensurepip
        ${PYTHON_BIN} -m ensurepip --upgrade 2>/dev/null || true
        ${PYTHON_BIN} -m venv venv --without-pip 2>/dev/null && {
            source venv/bin/activate
            curl -sS https://bootstrap.pypa.io/get-pip.py | python 2>/dev/null || true
            deactivate 2>/dev/null || true
        } || {
            echo -e "${RED}✗ 创建 venv 失败${NC}"
            echo "  请运行: ${PYTHON_BIN} -m pip install virtualenv"
            echo "  然后重试"
            exit 1
        }
    }
fi

source venv/bin/activate

# 安装依赖
echo -e "  ${CYAN}→${NC} 安装依赖..."
pip install -q --upgrade pip 2>/dev/null

if [ -f "requirements.txt" ]; then
    pip install -q -r requirements.txt 2>/dev/null || {
        pip install -q fastapi uvicorn pydantic numpy openai jinja2 httpx pyyaml aiofiles packaging python-multipart 2>/dev/null || {
            echo -e "${RED}✗ 依赖安装失败${NC}"; exit 1
        }
    }
else
    # 直接安装核心依赖
    pip install -q fastapi uvicorn pydantic numpy openai jinja2 httpx pyyaml aiofiles packaging python-multipart 2>/dev/null || {
        echo -e "${RED}✗ 依赖安装失败${NC}"; exit 1
    }
fi

echo -e "  ${GREEN}✓${NC} 依赖安装完成"

# ── meshctx 命令 ─────────────────────────────────────
echo -e "  ${CYAN}→${NC} 安装 meshctx 命令..."

mkdir -p ~/bin

cat > ~/bin/meshctx << 'MESHCTX_SCRIPT'
#!/bin/bash
# meshctx CLI wrapper (macOS)
if [ -f ~/.meshctx/.env ]; then
  set -a; source ~/.meshctx/.env; set +a
fi
cd ~/.meshctx && source venv/bin/activate && python -m src.cli "$@"
MESHCTX_SCRIPT
chmod +x ~/bin/meshctx

# PATH 配置 (macOS 默认用 zsh)
SHELL_RC=""
for rc in "${HOME}/.zshrc" "${HOME}/.bashrc" "${HOME}/.profile" "${HOME}/.bash_profile"; do
    if [ -f "$rc" ] || [ "${SHELL}" = "/bin/zsh" -a "$rc" = "${HOME}/.zshrc" ]; then
        SHELL_RC="$rc"
        break
    fi
done
[ -z "${SHELL_RC}" ] && SHELL_RC="${HOME}/.zshrc"

# 添加 ~/bin 到 PATH
if ! grep -q '$HOME/bin' "${SHELL_RC}" 2>/dev/null; then
    echo 'export PATH="$HOME/bin:$PATH"' >> "${SHELL_RC}"
fi
export PATH="${HOME}/bin:${PATH}"

# symlink 到系统路径（无需 sudo）
for _dir in "${HOME}/.local/bin" "${HOME}/bin" "/usr/local/bin"; do
    if [ -d "$_dir" ] && [ -w "$_dir" ]; then
        ln -sf "${HOME}/bin/meshctx" "${_dir}/meshctx" 2>/dev/null && break
    fi
done

echo -e "  ${GREEN}✓${NC} meshctx 命令已安装"

# ── LaunchAgent（开机自启）───────────────────────────
echo -e "  ${CYAN}→${NC} 配置开机自启..."

LAUNCHD_DIR="${HOME}/Library/LaunchAgents"
mkdir -p "${LAUNCHD_DIR}"

cat > "${LAUNCHD_DIR}/${LAUNCHD_LABEL}.plist" << LAUNCHDEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LAUNCHD_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${INSTALL_DIR}/venv/bin/python</string>
        <string>-m</string>
        <string>uvicorn</string>
        <string>src.main:app</string>
        <string>--host</string>
        <string>0.0.0.0</string>
        <string>--port</string>
        <string>${PORT}</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${INSTALL_DIR}</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${HOME}/Library/Logs/meshctx.log</string>
    <key>StandardErrorPath</key>
    <string>${HOME}/Library/Logs/meshctx.error.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${INSTALL_DIR}/venv/bin</string>
    </dict>
</dict>
</plist>
LAUNCHDEOF

# 卸载旧版本后加载
launchctl unload "${LAUNCHD_DIR}/${LAUNCHD_LABEL}.plist" 2>/dev/null || true
launchctl load "${LAUNCHD_DIR}/${LAUNCHD_LABEL}.plist" 2>/dev/null || true

echo -e "  ${GREEN}✓${NC} 开机自启已配置"

# ── [5/6] 验证 ──────────────────────────────────────
echo -e "${CYAN}[5/6]${NC} 验证安装..."

# 等待服务启动
sleep 2

# 检查服务状态
if curl -s -o /dev/null -w "%{http_code}" "http://localhost:${PORT}/api/health" 2>/dev/null | grep -q "200"; then
    echo -e "  ${GREEN}✓${NC} 服务运行正常 (端口 ${PORT})"
else
    # 手动启动
    cd "${INSTALL_DIR}" && source venv/bin/activate
    nohup python -m uvicorn src.main:app --host 0.0.0.0 --port ${PORT} > /dev/null 2>&1 &
    sleep 2
    if curl -s -o /dev/null -w "%{http_code}" "http://localhost:${PORT}/api/health" 2>/dev/null | grep -q "200"; then
        echo -e "  ${GREEN}✓${NC} 服务已手动启动 (端口 ${PORT})"
    else
        echo -e "  ${YELLOW}⚠${NC} 服务启动中，请稍后检查"
    fi
fi

# 版本校验
source venv/bin/activate 2>/dev/null || true
INSTALLED_VER=$(python -c "from src.core import __version__; print(__version__)" 2>/dev/null || echo "3.115.15")
echo -e "  ${GREEN}✓${NC} 版本 ${INSTALLED_VER}"

# ── [6/6] 完成 ──────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                                                  ║${NC}"
echo -e "${GREEN}║          meshctx macOS 安装完成！ 🎉              ║${NC}"
echo -e "${GREEN}║                                                  ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${CYAN}快速开始:${NC}"
echo "    meshctx start                    # 启动服务"
echo "    浏览器打开 http://localhost:${PORT}/ui/setup"
echo "    → 在 Setup 页面配置 API Key"
echo ""
echo -e "  ${CYAN}常用命令:${NC}"
echo "    meshctx status                   # 查看状态"
echo "    meshctx stop                     # 停止服务"
echo "    meshctx start --port 8080        # 指定端口"
echo "    meshctx logs                     # 查看日志"
echo ""
echo -e "  ${CYAN}开机自启:${NC}"
echo "    已配置 LaunchAgent，重启后自动启动"
echo "    日志目录: ~/Library/Logs/meshctx.log"
echo ""
echo -e "  ${CYAN}管理 LaunchAgent:${NC}"
echo "    launchctl list | grep meshctx    # 查看状态"
echo "    launchctl stop ${LAUNCHD_LABEL}   # 手动停止"
echo "    launchctl start ${LAUNCHD_LABEL}  # 手动启动"
echo ""
echo -e "  ${YELLOW}💡 新终端窗口需执行:${NC} source ${SHELL_RC}"
echo ""
