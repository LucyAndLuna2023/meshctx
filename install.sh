#!/bin/bash
# ============================================================
# meshctx 一键安装脚本
# 像安装 Hermes 一样简单：一条命令搞定
# ============================================================
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}"
echo "╔═══════════════════════════════════════════╗"
echo "║       meshctx v1.0 一键安装              ║"
echo "║   World's First Self-Evolving Agent      ║"
echo "╚═══════════════════════════════════════════╝"
echo -e "${NC}"

# 1. 检查 Python
echo -e "${YELLOW}[1/5] 检查环境...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}需要 Python 3.10+，请先安装${NC}"
    exit 1
fi

PYVER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "  Python $PYVER"

# 2. 创建虚拟环境
echo -e "${YELLOW}[2/5] 创建虚拟环境...${NC}"
INSTALL_DIR="${HOME}/.meshctx"
mkdir -p "$INSTALL_DIR"

if [ ! -d "$INSTALL_DIR/venv" ]; then
    python3 -m venv "$INSTALL_DIR/venv"
fi
source "$INSTALL_DIR/venv/bin/activate"

# 3. 安装
echo -e "${YELLOW}[3/5] 安装 meshctx...${NC}"
pip install -q --upgrade pip

if [ -f "pyproject.toml" ]; then
    # 从源码安装
    pip install -q -e .
else
    # 从 PyPI
    pip install -q meshctx
fi

# 安装额外依赖
pip install -q pytest-asyncio 2>/dev/null || true

# 4. 配置
echo -e "${YELLOW}[4/5] 配置...${NC}"
mkdir -p "$INSTALL_DIR/skills" "$INSTALL_DIR/cache" "$INSTALL_DIR/logs"

# 创建默认配置
cat > "$INSTALL_DIR/config.yaml" << 'EOF'
kernel:
  worker_count: 4
  log_level: info

models:
  default: bailian-free
  providers:
    bailian-free:
      provider: bailian
      model: qwen-turbo-latest
      base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
      api_key: "${BAILIAN_API_KEY}"

memory:
  embedding:
    provider: local
    model: hash

plugins:
  builtin:
    - memory
    - metacognition
    - orchestrator
    - predictor
    - agent_loop
    - performance
    - healer
    - websocket

gateway:
  enabled: false

skills:
  auto_create: true
  directory: "~/.meshctx/skills/"
EOF

# 5. 创建启动脚本
echo -e "${YELLOW}[5/5] 创建快捷命令...${NC}"

cat > "$INSTALL_DIR/bin/meshctx" << 'SCRIPT'
#!/bin/bash
source "${HOME}/.meshctx/venv/bin/activate"
exec python -m meshctx.cli "$@"
SCRIPT
chmod +x "$INSTALL_DIR/bin/meshctx"

# 添加到 PATH
SHELL_RC=""
if [ -f "$HOME/.bashrc" ]; then
    SHELL_RC="$HOME/.bashrc"
elif [ -f "$HOME/.zshrc" ]; then
    SHELL_RC="$HOME/.zshrc"
fi

if [ -n "$SHELL_RC" ] && ! grep -q "meshctx/bin" "$SHELL_RC" 2>/dev/null; then
    echo "export PATH=\"\$HOME/.meshctx/bin:\$PATH\"" >> "$SHELL_RC"
fi

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║       meshctx 安装完成!                  ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════╝${NC}"
echo ""
echo -e "  启动服务:  ${CYAN}meshctx start${NC}"
echo -e "  开始聊天:  ${CYAN}meshctx chat${NC}"
echo -e "  扫描模型:  ${CYAN}meshctx model scan${NC}"
echo -e "  Web界面:   ${CYAN}http://localhost:3000/ui/${NC}"
echo ""
echo -e "  ${YELLOW}提示: 运行 'source $SHELL_RC' 或新开终端使 PATH 生效${NC}"
echo ""
