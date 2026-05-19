#!/bin/bash
# ═══════════════════════════════════════════════════════
# meshctx 一键安装 v3
# curl -fsSL http://47.120.0.239:3001/install.sh | bash
# ═══════════════════════════════════════════════════════
set -e

GREEN='\033[0;32m'; CYAN='\033[0;36m'; RED='\033[0;31m'; NC='\033[0m'
INSTALL_DIR="${HOME}/.meshctx"
BASE="http://47.120.0.239:3001"

echo -e "${CYAN}"
echo "  meshctx 安装中..."
echo -e "${NC}"

python3 --version >/dev/null 2>&1 || { echo -e "${RED}需要Python 3.10+${NC}"; exit 1; }

# 下载源码包 (从同一服务器)
echo "→ 下载 meshctx ($BASE)..."
rm -rf "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR"

curl -fsSL "$BASE/static/dl/meshctx-src.tar.gz" -o /tmp/meshctx.tar.gz || {
    echo -e "${RED}下载失败: $BASE/static/dl/meshctx-src.tar.gz${NC}"
    echo "手动: git clone https://github.com/LucyAndLuna2023/meshctx.git $INSTALL_DIR"
    exit 1
}

tar -xzf /tmp/meshctx.tar.gz -C "$INSTALL_DIR" --strip-components=1
rm -f /tmp/meshctx.tar.gz

if [ ! -f "$INSTALL_DIR/src/main.py" ]; then
    echo -e "${RED}解压失败${NC}"
    exit 1
fi
echo "  ✓ 解压完成"

cd "$INSTALL_DIR"

# 虚拟环境
echo "→ 创建虚拟环境..."
python3 -m venv venv 2>/dev/null || { echo -e "${RED}venv失败: apt install python3-venv${NC}"; exit 1; }
source venv/bin/activate

# 依赖
echo "→ 安装依赖..."
pip install -q --upgrade pip 2>/dev/null
pip install -q fastapi uvicorn pydantic numpy openai jinja2 httpx pyyaml aiofiles packaging 2>/dev/null || {
    echo -e "${RED}依赖安装失败${NC}"
    exit 1
}
echo "  ✓ 依赖完成"

# 启动命令
mkdir -p ~/bin
cat > ~/bin/meshctx << 'SCRIPT'
#!/bin/bash
cd ~/.meshctx
source venv/bin/activate
python -m src.cli "$@"
SCRIPT
chmod +x ~/bin/meshctx
grep -q "$HOME/bin" ~/.bashrc 2>/dev/null || echo 'export PATH="$HOME/bin:$PATH"' >> ~/.bashrc
export PATH="$HOME/bin:$PATH"

echo ""
echo -e "${GREEN}安装完成!${NC}"
echo "  配置: meshctx setup"
echo "  启动: meshctx start"
echo ""

read -p "运行配置向导? [Y/n] " r
[[ "$r" != "n" && "$r" != "N" ]] && { source venv/bin/activate; python -m src.cli setup; }
