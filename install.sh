#!/bin/bash
# ═══════════════════════════════════════════════════════
# meshctx 一键安装 — 极简版
# curl -fsSL https://meshctx.com/install.sh | bash
# 
# 只负责: 下载 → 安装依赖 → 启动向导
# 模型/Key配置由首次启动时交互式完成
# ═══════════════════════════════════════════════════════
set -e

GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; NC='\033[0m'
INSTALL_DIR="${HOME}/.meshctx"

echo -e "${CYAN}"
echo "  ╔══════════════════════════════════╗"
echo "  ║     meshctx 安装中...           ║"
echo "  ╚══════════════════════════════════╝"
echo -e "${NC}"

# 1. Python检查
python3 --version >/dev/null 2>&1 || {
    echo "需要 Python 3.10+ — https://python.org"
    exit 1
}

# 2. 下载代码
if [ -d "$INSTALL_DIR/.git" ]; then
    echo "→ 更新..."
    cd "$INSTALL_DIR" && git pull --ff-only --quiet 2>/dev/null
else
    echo "→ 下载 meshctx..."
    git clone --depth 1 https://github.com/LucyAndLuna2023/meshctx.git "$INSTALL_DIR" 2>/dev/null || {
        echo "GitHub不可达。手动下载: https://github.com/LucyAndLuna2023/meshctx"
        exit 1
    }
fi
cd "$INSTALL_DIR"

# 3. 虚拟环境
if [ ! -d "venv" ]; then
    python3 -m venv venv
fi
source venv/bin/activate

# 4. 安装依赖
echo "→ 安装依赖..."
pip install -q --upgrade pip 2>/dev/null
pip install -q fastapi uvicorn pydantic numpy openai jinja2 httpx pyyaml aiofiles 2>/dev/null

# 5. 创建启动命令
mkdir -p ~/bin
cat > ~/bin/meshctx << 'EOF'
#!/bin/bash
cd ~/.meshctx
source venv/bin/activate
python -m src.cli "$@"
EOF
chmod +x ~/bin/meshctx
grep -q 'PATH.*~/bin' ~/.bashrc 2>/dev/null || echo 'export PATH="$HOME/bin:$PATH"' >> ~/.bashrc
export PATH="$HOME/bin:$PATH"

# 6. 完成
echo ""
echo -e "${GREEN}  安装完成!${NC}"
echo ""
echo -e "  首次启动配置向导:  ${CYAN}meshctx setup${NC}"
echo -e "  启动Web界面:        ${CYAN}meshctx start${NC}"
echo -e "  聊天:               ${CYAN}meshctx chat${NC}"
echo ""
echo -e "  配置文档: ${CYAN}https://meshctx.com/docs/config${NC}"
echo ""

# 询问是否立即配置
read -p "是否现在运行配置向导? [Y/n] " run_setup
if [[ "$run_setup" != "n" && "$run_setup" != "N" ]]; then
    source venv/bin/activate
    python -m src.cli setup
fi
