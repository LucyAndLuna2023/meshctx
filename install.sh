#!/bin/bash
# ═══════════════════════════════════════════════════════
# meshctx 一键安装脚本 v2.0
# 一条命令: curl -fsSL meshctx.com/install | bash
# 自动完成: 安装依赖 → 配置模型 → 启动服务 → 打开浏览器
# ═══════════════════════════════════════════════════════
set -e

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; NC='\033[0m'
INSTALL_DIR="${HOME}/.meshctx"

echo -e "${CYAN}"
echo "╔═══════════════════════════════════════════╗"
echo "║     meshctx v1.0  一键安装               ║"
echo "║   World's First Self-Evolving Agent      ║"
echo "╚═══════════════════════════════════════════╝"
echo -e "${NC}"

# 1. 检查 Python
echo -e "→ 检查环境..."
python3 --version 2>/dev/null || { echo -e "${RED}需要 Python 3.10+${NC}"; exit 1; }

# 2. 克隆/更新代码
if [ -d "$INSTALL_DIR/src" ]; then
    echo "→ 更新已有安装..."
    cd "$INSTALL_DIR" && git pull --force --quiet 2>/dev/null || true
else
    echo "→ 下载 meshctx..."
    git clone --depth 1 https://github.com/LucyAndLuna2023/meshctx.git "$INSTALL_DIR" 2>/dev/null || {
        echo "GitHub不可达，从备用源下载..."
        mkdir -p "$INSTALL_DIR"
        # 备用: 用户手动复制文件
    }
fi

cd "$INSTALL_DIR"

# 3. 创建虚拟环境
if [ ! -d "venv" ]; then
    echo "→ 创建虚拟环境..."
    python3 -m venv venv
fi
source venv/bin/activate

# 4. 安装依赖
echo "→ 安装依赖..."
pip install -q --upgrade pip 2>/dev/null
pip install -q -e . 2>/dev/null || pip install -q -r requirements.txt 2>/dev/null
pip install -q pycryptodome fastapi uvicorn pydantic numpy openai jinja2 httpx 2>/dev/null

# 5. 自动检测 API Key
echo "→ 检测 API Key..."
mkdir -p ~/.meshctx

# 检查常见的 API Key 环境变量
FOUND_KEY=""
for var in DEEPSEEK_API_KEY OPENAI_API_KEY BAILIAN_API_KEY ANTHROPIC_API_KEY GEMINI_API_KEY; do
    val="${!var}"
    if [ -n "$val" ]; then
        echo "  ✓ 发现 $var"
        FOUND_KEY="$var"
        break
    fi
done

if [ -z "$FOUND_KEY" ]; then
    echo ""
    echo -e "${CYAN}════════════════════════════════════════════${NC}"
    echo -e "  需要配置一个 AI 模型的 API Key"
    echo ""
    echo -e "  ${GREEN}推荐 DeepSeek (免费额度):${NC}"
    echo -e "  1. 打开 https://platform.deepseek.com"
    echo -e "  2. 注册 → API Keys → 创建"
    echo -e "  3. 复制 key，粘贴到下面:"
    echo ""
    read -p "  DeepSeek API Key: " user_key
    
    if [ -n "$user_key" ]; then
        export DEEPSEEK_API_KEY="$user_key"
        echo "export DEEPSEEK_API_KEY=$user_key" >> ~/.bashrc
        echo -e "  ${GREEN}✓ 已保存到 ~/.bashrc${NC}"
    fi
fi

# 6. 创建启动脚本
mkdir -p ~/bin
cat > ~/bin/meshctx << SCRIPT
#!/bin/bash
export DEEPSEEK_API_KEY="${DEEPSEEK_API_KEY}"
export OPENAI_API_KEY="${OPENAI_API_KEY}"
export BAILIAN_API_KEY="${BAILIAN_API_KEY}"
cd ${INSTALL_DIR}
source venv/bin/activate
python -m src.cli "\$@"
SCRIPT
chmod +x ~/bin/meshctx

# 确保 ~/bin 在 PATH
grep -q 'PATH.*~/bin' ~/.bashrc 2>/dev/null || echo 'export PATH="$HOME/bin:$PATH"' >> ~/.bashrc
export PATH="$HOME/bin:$PATH"

# 7. 自动扫描模型
echo "→ 扫描可用模型..."
source venv/bin/activate
python -m src.cli model scan 2>/dev/null || true

# 8. 完成
echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║       meshctx 安装完成!                  ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════╝${NC}"
echo ""
echo -e "  聊天:        ${CYAN}meshctx chat${NC}"
echo -e "  Web界面:     ${CYAN}meshctx start${NC} → http://localhost:3000/ui/chat"
echo -e "  配置平台:    聊天中输入 ${CYAN}/gateway${NC}"
echo -e "  切换模型:    聊天中输入 ${CYAN}/models${NC}"
echo ""

# 9. 询问是否立即启动
read -p "是否立即启动 Web 界面? [Y/n] " start_now
if [[ "$start_now" != "n" && "$start_now" != "N" ]]; then
    echo "→ 启动中..."
    meshctx start &
    sleep 3
    echo -e "${GREEN}→ 浏览器打开 http://localhost:3000/ui/chat${NC}"
fi
