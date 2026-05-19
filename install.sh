#!/bin/bash
# ═══════════════════════════════════════════════════════
# meshctx 一键安装 v2
# curl -fsSL https://meshctx.com/install.sh | bash
# 
# 自动: 下载 → 安装依赖 → 引导配置
# ═══════════════════════════════════════════════════════
set -e

GREEN='\033[0;32m'; CYAN='\033[0;36m'; RED='\033[0;31m'; NC='\033[0m'
INSTALL_DIR="${HOME}/.meshctx"
SOURCE_URL="https://meshctx.com/dl/meshctx-src.tar.gz"
GITHUB_URL="https://github.com/LucyAndLuna2023/meshctx.git"

echo -e "${CYAN}"
echo "  ╔══════════════════════════════════╗"
echo "  ║     meshctx 安装中...           ║"
echo "  ╚══════════════════════════════════╝"
echo -e "${NC}"

# 1. 检查 Python
python3 --version >/dev/null 2>&1 || {
    echo -e "${RED}需要 Python 3.10+ — https://python.org${NC}"
    exit 1
}

# 2. 下载代码 (优先meshctx.com，回退GitHub)
echo "→ 下载 meshctx..."
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "  更新已有安装..."
    cd "$INSTALL_DIR"
    git pull --ff-only --quiet 2>/dev/null || echo "  (更新跳过，使用本地版本)"
else
    # 尝试从meshctx.com下载
    if command -v curl &>/dev/null; then
        curl -fsSL "$SOURCE_URL" -o /tmp/meshctx-src.tar.gz 2>/dev/null && {
            echo "  ✓ 从 meshctx.com 下载"
            mkdir -p "$INSTALL_DIR"
            tar -xzf /tmp/meshctx-src.tar.gz -C "$INSTALL_DIR" --strip-components=1 2>/dev/null
            rm -f /tmp/meshctx-src.tar.gz
        }
    fi
    
    # 如果上面失败，尝试GitHub
    if [ ! -f "$INSTALL_DIR/src/main.py" ]; then
        echo "  尝试 GitHub..."
        if command -v git &>/dev/null; then
            git clone --depth 1 "$GITHUB_URL" "$INSTALL_DIR" 2>/dev/null || true
        fi
    fi
    
    # 还是失败
    if [ ! -f "$INSTALL_DIR/src/main.py" ]; then
        echo -e "${RED}下载失败。请手动安装:${NC}"
        echo "  git clone $GITHUB_URL $INSTALL_DIR"
        exit 1
    fi
fi

cd "$INSTALL_DIR"

# 3. 虚拟环境
echo "→ 创建虚拟环境..."
if [ ! -d "venv" ]; then
    python3 -m venv venv 2>/dev/null || {
        echo -e "${RED}创建venv失败。请安装: apt install python3-venv${NC}"
        exit 1
    }
fi
source venv/bin/activate

# 4. 安装依赖
echo "→ 安装依赖..."
pip install -q --upgrade pip 2>/dev/null
pip install -q fastapi uvicorn pydantic numpy openai jinja2 httpx pyyaml aiofiles 2>/dev/null || {
    echo -e "${RED}依赖安装失败。请检查网络连接。${NC}"
    exit 1
}
echo "  ✓ 依赖安装完成"

# 5. 创建启动命令
mkdir -p ~/bin
cat > ~/bin/meshctx << 'SCRIPT'
#!/bin/bash
cd ~/.meshctx
source venv/bin/activate
python -m src.cli "$@"
SCRIPT
chmod +x ~/bin/meshctx

# 添加到PATH
if ! echo "$PATH" | grep -q "$HOME/bin"; then
    echo 'export PATH="$HOME/bin:$PATH"' >> ~/.bashrc
    export PATH="$HOME/bin:$PATH"
fi

# 6. 完成
echo ""
echo -e "${GREEN}  ╔══════════════════════════════════╗"
echo "  ║     安装完成!                   ║"
echo "  ╚══════════════════════════════════╝${NC}"
echo ""
echo "  配置向导:  meshctx setup    (交互式选择模型+Key)"
echo "  启动服务:  meshctx start    (Web界面)"
echo "  聊天:      meshctx chat"
echo ""

# 7. 询问配置
read -p "是否现在运行配置向导? [Y/n] " run_setup
if [[ "$run_setup" != "n" && "$run_setup" != "N" ]]; then
    cd "$INSTALL_DIR"
    source venv/bin/activate
    python -m src.cli setup
fi
