#!/bin/bash
# ═══════════════════════════════════════════════════════
# meshctx 一键安装
# curl -fsSL https://raw.githubusercontent.com/LucyAndLuna2023/meshctx/main/install.sh | bash
# ═══════════════════════════════════════════════════════
set -e

GREEN='\033[0;32m'; CYAN='\033[0;36m'; RED='\033[0;31m'; NC='\033[0m'
INSTALL_DIR="${HOME}/.meshctx"
REPO="https://github.com/LucyAndLuna2023/meshctx.git"

echo -e "${CYAN}"
echo "  meshctx 安装中..."
echo -e "${NC}"

python3 --version >/dev/null 2>&1 || { echo -e "${RED}需要 Python 3.10+${NC}"; exit 1; }

echo "→ git clone..."
if [ -d "$INSTALL_DIR/.git" ]; then
    cd "$INSTALL_DIR" && git pull --ff-only --quiet 2>/dev/null && echo "  ✓ 已更新"
else
    git clone --depth 1 "$REPO" "$INSTALL_DIR" 2>/dev/null || {
        echo -e "${RED}git clone 失败${NC}"
        echo "  手动: git clone $REPO $INSTALL_DIR"
        exit 1
    }
    echo "  ✓ 克隆完成"
fi

cd "$INSTALL_DIR"

echo "→ 创建 venv..."
python3 -m venv venv 2>/dev/null || { echo -e "${RED}venv失败: apt install python3-venv${NC}"; exit 1; }
source venv/bin/activate

echo "→ 安装依赖..."
pip install -q --upgrade pip 2>/dev/null
pip install -q -r requirements.txt 2>/dev/null || pip install -q fastapi uvicorn pydantic numpy openai jinja2 httpx pyyaml aiofiles packaging 2>/dev/null || {
    echo -e "${RED}依赖安装失败${NC}"
    exit 1
}
echo "  ✓ 依赖完成"

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
