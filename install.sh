#!/bin/bash
# ═══════════════════════════════════════════════════════
# meshctx 一键安装 v8
# 使用: curl -fsSL https://raw.githubusercontent.com/LucyAndLuna2023/meshctx/main/install.sh | bash
# ═══════════════════════════════════════════════════════
set -e

GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[0;33m'; RED='\033[0;31m'; NC='\033[0m'
INSTALL_DIR="${HOME}/.meshctx"
VERSION="3.115.11"
REPO="LucyAndLuna2023/meshctx"
SRC_URL="https://github.com/${REPO}/releases/download/v${VERSION}/meshctx-src.tar.gz"
PORT=3001

echo ""
echo -e "${CYAN}  ╔══════════════════════════════════════════╗${NC}"
echo -e "${CYAN}  ║     meshctx v${VERSION} 一键安装              ║${NC}"
echo -e "${CYAN}  ╚══════════════════════════════════════════╝${NC}"
echo ""

# ── 停止旧版本 ──────────────────────────────────────
echo -e "${CYAN}[1/5]${NC} 停止旧版本..."
KILLED=0
# 停止本机 uvicorn
if pgrep -f "uvicorn.*src.main" >/dev/null 2>&1; then
    pkill -9 -f "uvicorn.*src.main" 2>/dev/null || true
    KILLED=1
fi
# 停止 meshctx CLI 进程
if pgrep -f "python.*meshctx" >/dev/null 2>&1; then
    pkill -9 -f "python.*meshctx" 2>/dev/null || true
    KILLED=1
fi
sleep 1

# 释放端口
if command -v ss >/dev/null 2>&1; then
    PORT_PID=$(ss -tlnp 2>/dev/null | grep ":${PORT} " | grep -oP 'pid=\K[0-9]+' | head -1)
elif command -v lsof >/dev/null 2>&1; then
    PORT_PID=$(lsof -ti:${PORT} 2>/dev/null | head -1)
else
    PORT_PID=""
fi
if [ -n "$PORT_PID" ]; then
    kill -9 "$PORT_PID" 2>/dev/null || true
    KILLED=1
fi

if [ "$KILLED" = "1" ]; then
    echo -e "  ${GREEN}✓${NC} 已停止旧服务并释放端口 ${PORT}"
else
    echo -e "  ${GREEN}✓${NC} 无需停止"
fi

# ── 检查 Python ──────────────────────────────────────
echo -e "${CYAN}[2/5]${NC} 检查环境..."
python3 --version >/dev/null 2>&1 || {
    echo -e "${RED}✗ 需要 Python 3.10+，请先安装: apt install python3${NC}"
    exit 1
}
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_OK=$(python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null && echo 1 || echo 0)
if [ "$PY_OK" = "0" ]; then
    echo -e "${RED}✗ 需要 Python 3.10+，当前 ${PY_VER}${NC}"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} Python ${PY_VER}"

# ── 下载 ────────────────────────────────────────────
echo -e "${CYAN}[3/5]${NC} 下载 meshctx v${VERSION}..."
TMPDIR=$(mktemp -d)
TARBALL="${TMPDIR}/meshctx-src.tar.gz"
trap "rm -rf ${TMPDIR}" EXIT

DOWNLOAD_OK=0
if command -v wget >/dev/null 2>&1; then
    wget -q --timeout=120 --tries=3 -O "${TARBALL}" "${SRC_URL}" && DOWNLOAD_OK=1
else
    curl -fsSL --connect-timeout 60 --retry 3 -o "${TARBALL}" "${SRC_URL}" && DOWNLOAD_OK=1
fi

if [ "$DOWNLOAD_OK" != "1" ]; then
    echo -e "${RED}✗ 下载失败${NC}"
    echo "  请检查网络连接，或手动下载:"
    echo "  ${SRC_URL}"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} 下载完成 ($(du -h "${TARBALL}" | cut -f1))"

# ── 备份用户配置 ────────────────────────────────────
echo -e "${CYAN}[4/6]${NC} 安装中..."
CONFIG_BACKUP=""
if [ -d "${INSTALL_DIR}" ]; then
    # 备份用户的重要配置文件（Key、模型配置等）
    CONFIG_BACKUP=$(mktemp -d)
    for f in config.yaml .env provider_config.json; do
        if [ -f "${INSTALL_DIR}/${f}" ]; then
            cp "${INSTALL_DIR}/${f}" "${CONFIG_BACKUP}/${f}" 2>/dev/null || true
        fi
    done
    # 也备份项目根目录的 provider_config.json（如果在别处）
    [ -z "$CONFIG_BACKUP" ] || echo -e "  ${GREEN}✓${NC} 已备份用户配置"
fi

rm -rf "${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"
tar xzf "${TARBALL}" -C "${INSTALL_DIR}" || {
    echo -e "${RED}✗ 解压失败${NC}"; exit 1
}

# ── 恢复用户配置 ────────────────────────────────────
if [ -n "$CONFIG_BACKUP" ] && [ -d "$CONFIG_BACKUP" ]; then
    RESTORED=0
    for f in config.yaml .env; do
        if [ -f "${CONFIG_BACKUP}/${f}" ]; then
            cp "${CONFIG_BACKUP}/${f}" "${INSTALL_DIR}/${f}" 2>/dev/null || true
            RESTORED=1
        fi
    done
    # provider_config.json 位于项目根目录
    if [ -f "${CONFIG_BACKUP}/provider_config.json" ]; then
        cp "${CONFIG_BACKUP}/provider_config.json" "${INSTALL_DIR}/provider_config.json" 2>/dev/null || true
        RESTORED=1
    fi
    # 🔒 安全: 永远不恢复旧密码，新安装默认无需密码
    if [ -f "${INSTALL_DIR}/.env" ]; then
        sed -i '/^MESHCTX_PASSWORD=/d' "${INSTALL_DIR}/.env" 2>/dev/null || true
    fi
    rm -rf "$CONFIG_BACKUP"
    [ "$RESTORED" = "0" ] || echo -e "  ${GREEN}✓${NC} 用户配置已恢复（API Key / 模型配置不丢失，密码已重置）"
fi

cd "${INSTALL_DIR}"

# venv — robust creation with multiple fallbacks
PYTHON_BIN=""
for p in python3 python3.11 python3.12 python3.10 python; do
    if command -v "$p" >/dev/null 2>&1; then
        ver=$($p --version 2>&1 | grep -oP '\d+\.\d+' | head -1)
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 8 ] 2>/dev/null; then
            PYTHON_BIN="$p"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo -e "${RED}✗ 未找到 Python >= 3.8，请先安装 Python${NC}"
    echo -e "  Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
    echo -e "  CentOS/RHEL:   sudo yum install python3 python3-pip"
    echo -e "  macOS:         brew install python@3.12"
    exit 1
fi

echo -e "  ${CYAN}→${NC} 使用 Python: $PYTHON_BIN ($($PYTHON_BIN --version))"

if [ ! -d "venv" ]; then
    # Try standard venv first
    $PYTHON_BIN -m venv venv 2>/dev/null || {
        # Fallback: ensurepip + venv
        $PYTHON_BIN -m ensurepip --upgrade 2>/dev/null || true
        $PYTHON_BIN -m venv venv --without-pip 2>/dev/null && {
            source venv/bin/activate
            curl -sS https://bootstrap.pypa.io/get-pip.py | $PYTHON_BIN 2>/dev/null || true
        } || {
            # Last resort: virtualenv
            pip install virtualenv 2>/dev/null || $PYTHON_BIN -m pip install virtualenv 2>/dev/null
            $PYTHON_BIN -m virtualenv venv 2>/dev/null || {
                echo -e "${RED}✗ 创建 venv 失败${NC}"
                echo -e "  Ubuntu/Debian: sudo apt install python3-venv python3-pip"
                echo -e "  CentOS/RHEL:   sudo yum install python3-pip && pip3 install virtualenv"
                echo -e "  Arch:          sudo pacman -S python-virtualenv"
                exit 1
            }
        }
    }
fi
source venv/bin/activate

# 依赖
pip install -q --upgrade pip 2>/dev/null
pip install -q -r requirements.txt 2>/dev/null || {
    pip install -q fastapi uvicorn pydantic numpy openai jinja2 httpx pyyaml aiofiles packaging python-multipart 2>/dev/null || {
        echo -e "${RED}✗ 依赖安装失败${NC}"; exit 1
    }
}

# meshctx 命令
mkdir -p ~/bin
cat > ~/bin/meshctx << 'SCRIPT'
#!/bin/bash
if [ -f ~/.meshctx/.env ]; then
  set -a; source ~/.meshctx/.env; set +a
fi
cd ~/.meshctx && source venv/bin/activate && python -m src.cli "$@"
SCRIPT
chmod +x ~/bin/meshctx

# PATH — 支持 bash/zsh/fish
SHELL_RC=""
for rc in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.profile" "$HOME/.bash_profile"; do
    if [ -f "$rc" ] || [ "$SHELL" = "/bin/zsh" -a "$rc" = "$HOME/.zshrc" ]; then
        SHELL_RC="$rc"
        break
    fi
done
[ -z "$SHELL_RC" ] && SHELL_RC="$HOME/.bashrc"

if ! echo "$PATH" | grep -q "$HOME/bin"; then
    echo "export PATH=\"\$HOME/bin:\$PATH\"" >> "$SHELL_RC"
fi
export PATH="$HOME/bin:$PATH"

# 系统级 symlink — 不强制 sudo，优先用 ~/.local/bin（用户可写）
SYMLINK_OK=0
for _dir in "$HOME/.local/bin" "$HOME/bin"; do
    if [ -d "$_dir" ] && [ -w "$_dir" ]; then
        ln -sf "$HOME/bin/meshctx" "$_dir/meshctx" 2>/dev/null && SYMLINK_OK=1 && break
    fi
done
# 兜底：/usr/local/bin 可写则写，否则跳过（不再弹 sudo）
if [ "$SYMLINK_OK" = "0" ]; then
    if [ -w /usr/local/bin ]; then
        ln -sf "$HOME/bin/meshctx" /usr/local/bin/meshctx 2>/dev/null && SYMLINK_OK=1
    fi
fi

echo -e "  ${GREEN}✓${NC} 安装完成"

# ── 验证 ────────────────────────────────────────────
echo -e "${CYAN}[5/6]${NC} 验证安装..."
source venv/bin/activate
INSTALLED_VER=$(python -c "from src.core import __version__; print(__version__)" 2>/dev/null || echo "?")
if [ "$INSTALLED_VER" = "$VERSION" ]; then
    echo -e "  ${GREEN}✓${NC} 版本 ${INSTALLED_VER} 校验通过"
else
    echo -e "  ${YELLOW}⚠${NC} 版本 ${INSTALLED_VER}（期望 ${VERSION}）"
fi

# ── 完成 ────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                                                  ║${NC}"
echo -e "${GREEN}║          meshctx 安装完成！ 🎉                     ║${NC}"
echo -e "${GREEN}║                                                  ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════╝${NC}"
echo ""
if [ "$KILLED" = "1" ]; then
    echo -e "  ${GREEN}✓${NC} 已自动停止旧进程，新版本不会冲突"
fi
echo -e "  ${CYAN}快速开始:${NC}"
echo "    meshctx start                    # 启动服务"
echo "    浏览器打开 http://localhost:${PORT}/ui/setup"
echo "    → 在 Setup 页面配置 API Key"
echo "    → 打开 Dashboard 查看状态"
echo ""
echo -e "  ${YELLOW}💡 提示:${NC} 首次打开页面请按 ${BOLD}Ctrl+Shift+R${NC} 强制刷新浏览器缓存"
echo ""
echo -e "  ${CYAN}常用命令:${NC}"
echo "    meshctx status                   # 查看状态"
echo "    meshctx stop                     # 停止服务"
echo "    meshctx start --port 8080        # 指定端口"
echo ""
echo -e "  ${YELLOW}💡 提示：${NC}如果页面显示异常，按 Ctrl+Shift+R 强制刷新浏览器缓存"
echo ""
echo -e "  ${GREEN}👉 现在运行:${NC}  meshctx start    # 启动服务"
[ "$SYMLINK_OK" = "1" ] && echo -e "  ${GREEN}✓${NC} meshctx 命令已加入 PATH（无需 sudo）"
echo -e "  ${YELLOW}💡${NC} 新终端窗口需执行: source $SHELL_RC    # 或重新打开终端"
echo ""
