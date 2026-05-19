#!/bin/bash
# ═══════════════════════════════════════════════════════
# meshctx 一键安装脚本 v3.1
# 从 meshctx 服务器直接下载，无需 GitHub/代理
# curl -fsSL https://meshctx.com/install.sh | bash
# ═══════════════════════════════════════════════════════
set -e

GREEN='\033[0;32m'; CYAN='\033[0;36m'; RED='\033[0;31m'; NC='\033[0m'
INSTALL_DIR="${HOME}/.meshctx"
VERSION="2.29.3"

# 下载地址优先级：域名 → IP (防止DNS未配置)
DL_HOSTS=("meshctx.com" "47.120.0.239")
SRC_PATH="/dl/meshctx-src.tar.gz"

echo -e "${CYAN}"
echo "  ╔══════════════════════════════════════════╗"
echo "  ║     meshctx v${VERSION} 一键安装              ║"
echo "  ╚══════════════════════════════════════════╝"
echo -e "${NC}"

# ── 检查 Python ──
echo "→ 检查 Python..."
if ! python3 --version >/dev/null 2>&1; then
    echo -e "${RED}✗ 需要 Python 3.10+，请先安装:${NC}"
    echo "  Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip"
    echo "  CentOS/RHEL:   sudo yum install python3"
    echo "  macOS:         brew install python@3.12"
    exit 1
fi
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo -e "  ${GREEN}✓${NC} Python ${PY_VER}"

# ── 查找最佳下载源 ──
echo "→ 查找最佳下载源..."
TMPDIR=$(mktemp -d)
TARBALL="${TMPDIR}/meshctx-src.tar.gz"
trap "rm -rf ${TMPDIR}" EXIT

DOWNLOAD_OK=0
DL_HOST=""
for host in "${DL_HOSTS[@]}"; do
    DL_URL="https://${host}${SRC_PATH}"
    echo "  尝试 ${host}..."
    if command -v wget >/dev/null 2>&1; then
        wget -q --no-check-certificate --timeout=15 -O "${TARBALL}" "${DL_URL}" 2>/dev/null && DOWNLOAD_OK=1
    else
        curl -fskL --connect-timeout 15 -o "${TARBALL}" "${DL_URL}" 2>/dev/null && DOWNLOAD_OK=1
    fi
    if [ "$DOWNLOAD_OK" = "1" ]; then
        DL_HOST="${host}"
        break
    fi
done

if [ "$DOWNLOAD_OK" != "1" ]; then
    echo -e "${RED}✗ 所有下载源均失败${NC}"
    echo "  请检查网络或手动安装: https://github.com/LucyAndLuna2023/meshctx"
    exit 1
fi
echo -e "  ${GREEN}✓${NC} 从 ${DL_HOST} 下载完成 ($(du -h "${TARBALL}" | cut -f1))"

# ── 解压到安装目录 ──
echo "→ 解压到 ${INSTALL_DIR}..."
rm -rf "${INSTALL_DIR}"
mkdir -p "${INSTALL_DIR}"
tar xzf "${TARBALL}" -C "${INSTALL_DIR}" --strip-components=1 || {
    echo -e "${RED}✗ 解压失败${NC}"
    exit 1
}
echo -e "  ${GREEN}✓${NC} 解压完成"

cd "${INSTALL_DIR}"

# ── 创建虚拟环境 ──
echo "→ 创建 Python 虚拟环境..."
python3 -m venv venv 2>/dev/null || {
    echo -e "${RED}✗ venv创建失败，请安装: apt install python3-venv${NC}"
    exit 1
}
source venv/bin/activate
echo -e "  ${GREEN}✓${NC} venv 就绪"

# ── 安装依赖 ──
echo "→ 安装 Python 依赖..."
pip install -q --upgrade pip 2>/dev/null
pip install -q -r requirements.txt 2>/dev/null || {
    pip install -q fastapi uvicorn pydantic numpy openai jinja2 httpx pyyaml aiofiles packaging 2>/dev/null || {
        echo -e "${RED}✗ 依赖安装失败${NC}"
        exit 1
    }
}
echo -e "  ${GREEN}✓${NC} 依赖完成"

# ── 创建启动命令 ──
mkdir -p ~/bin
cat > ~/bin/meshctx << 'SCRIPT'
#!/bin/bash
INSTALL_DIR="${HOME}/.meshctx"
cd "${INSTALL_DIR}"
source venv/bin/activate
python -m src.cli "$@"
SCRIPT
chmod +x ~/bin/meshctx

if ! grep -q "$HOME/bin" ~/.bashrc 2>/dev/null; then
    echo 'export PATH="$HOME/bin:$PATH"' >> ~/.bashrc
fi
export PATH="$HOME/bin:$PATH"

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║         meshctx 安装完成!                  ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""
echo "  快速开始:"
echo "    meshctx setup    # 配置 API Key"
echo "    meshctx start    # 启动服务"
echo ""

read -p "是否运行配置向导? [Y/n] " r
if [[ "$r" != "n" && "$r" != "N" ]]; then
    source venv/bin/activate
    python -m src.cli setup
fi
