#!/bin/bash
# ═══════════════════════════════════════════════════════
# meshctx 一键安装 v6
# curl -fsSL https://raw.githubusercontent.com/LucyAndLuna2023/meshctx/main/install.sh | bash
# ═══════════════════════════════════════════════════════
set -e

GREEN='\033[0;32m'; CYAN='\033[0;36m'; RED='\033[0;31m'; NC='\033[0m'
INSTALL_DIR="${HOME}/.meshctx"
VERSION="2.36.0"
REPO="LucyAndLuna2023/meshctx"
SRC_URL="https://github.com/${REPO}/releases/download/v${VERSION}/meshctx-src.tar.gz"

echo -e "${CYAN}"
echo "  ╔══════════════════════════════════════════╗"
echo "  ║     meshctx v${VERSION} 一键安装              ║"
echo "  ╚══════════════════════════════════════════╝"
echo -e "${NC}"

# ── 检查 Python ──
echo "→ 检查 Python..."
python3 --version >/dev/null 2>&1 || {
    echo -e "${RED}✗ 需要 Python 3.10+${NC}"
    exit 1
}
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo -e "  ${GREEN}✓${NC} Python ${PY_VER}"

# ── 下载源码包 ──
echo "→ 下载源码包..."
TMPDIR=$(mktemp -d)
TARBALL="${TMPDIR}/meshctx-src.tar.gz"
trap "rm -rf ${TMPDIR}" EXIT

if command -v wget >/dev/null 2>&1; then
    wget -q --timeout=60 -O "${TARBALL}" "${SRC_URL}" || {
        echo -e "${RED}✗ 下载失败${NC}"
        echo "  手动安装: git clone https://github.com/${REPO}.git ${INSTALL_DIR}"
        exit 1
    }
else
    curl -fsSL --connect-timeout 60 -o "${TARBALL}" "${SRC_URL}" || {
        echo -e "${RED}✗ 下载失败${NC}"
        echo "  手动安装: git clone https://github.com/${REPO}.git ${INSTALL_DIR}"
        exit 1
    }
fi
echo -e "  ${GREEN}✓${NC} 下载完成 ($(du -h "${TARBALL}" | cut -f1))"

# ── 解压 ──
echo "→ 解压到 ${INSTALL_DIR}..."
rm -rf "${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"
tar xzf "${TARBALL}" -C "${INSTALL_DIR}" || {
    echo -e "${RED}✗ 解压失败${NC}"
    exit 1
}
echo -e "  ${GREEN}✓${NC} 解压完成"

cd "${INSTALL_DIR}"

# ── venv + 依赖 ──
echo "→ 创建 venv..."
python3 -m venv venv 2>/dev/null || { echo -e "${RED}✗ venv失败 (apt install python3-venv)${NC}"; exit 1; }
source venv/bin/activate
echo -e "  ${GREEN}✓${NC} venv 就绪"

echo "→ 安装依赖..."
pip install -q --upgrade pip 2>/dev/null
pip install -q -r requirements.txt 2>/dev/null || {
    pip install -q fastapi uvicorn pydantic numpy openai jinja2 httpx pyyaml aiofiles packaging python-multipart 2>/dev/null || {
        echo -e "${RED}✗ 依赖安装失败${NC}"; exit 1
    }
}
echo -e "  ${GREEN}✓${NC} 依赖完成"

# ── meshctx 命令 ──
mkdir -p ~/bin
cat > ~/bin/meshctx << 'SCRIPT'
#!/bin/bash
# 加载API Key
if [ -f ~/.meshctx/.env ]; then
  set -a; source ~/.meshctx/.env; set +a
fi
cd ~/.meshctx && source venv/bin/activate && python -m src.cli "$@"
SCRIPT
chmod +x ~/bin/meshctx
grep -q "$HOME/bin" ~/.bashrc 2>/dev/null || echo 'export PATH="$HOME/bin:$PATH"' >> ~/.bashrc
export PATH="$HOME/bin:$PATH"

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         meshctx 安装完成!                  ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""
echo "  meshctx setup    # 配置 API Key"
echo "  meshctx start    # 启动"
echo ""

echo "  安装完成后执行:"
echo ""
echo "    ~/bin/meshctx setup    # 配置 API Key 和模型"
echo "    ~/bin/meshctx start    # 启动服务"
echo ""
echo "  然后访问 http://localhost:8888"
