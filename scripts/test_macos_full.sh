#!/bin/bash
# MeshCtx macOS 全量兼容性验证脚本
# 在 macOS 上运行: bash test_macos_full.sh
# Linux 上模拟验证: bash test_macos_full.sh --dry-run

set -e
echo "═══════════════════════════════════════"
echo " MeshCtx macOS 全量测试 v3.115.16"
echo "═══════════════════════════════════════"

DRY_RUN=false
[ "$1" = "--dry-run" ] && DRY_RUN=true && echo "⚠️  模拟模式 - 仅检查代码，不执行"

# ── 1. 环境检查 ──
echo ""
echo "【1/8】环境检查"
if [ "$DRY_RUN" = false ]; then
    echo "  OS: $(sw_vers -productName 2>/dev/null || echo 'unknown') $(sw_vers -productVersion 2>/dev/null)"
    echo "  Arch: $(uname -m)"
    echo "  Python: $(python3 --version 2>/dev/null || echo 'not found')"
    echo "  pip: $(pip3 --version 2>/dev/null | head -1 || echo 'not found')"
    # Check for brew
    which brew >/dev/null 2>&1 && echo "  brew: $(brew --version | head -1)" || echo "  brew: NOT INSTALLED"
else
    echo "  (dry-run: skipping system checks)"
fi

# ── 2. 依赖检查 ──
echo ""
echo "【2/8】依赖兼容性"
for pkg in "fastapi" "uvicorn" "jinja2" "numpy" "pyyaml" "websockets"; do
    if [ "$DRY_RUN" = false ]; then
        python3 -c "import $pkg" 2>/dev/null && echo "  ✅ $pkg" || echo "  ❌ $pkg - pip3 install $pkg"
    else
        echo "  ✅ $pkg (dry-run)"
    fi
done

# ── 3. 代码导入验证 ──
echo ""
echo "【3/8】核心模块导入"
MODULES=(
    "src.main" "src.web_ui" "src.cli" "src.i18n"
    "src.core.memory_engine" "src.core.knowledge_synth"
    "src.core.orchestrator" "src.core.plugin_manager"
    "src.core.brain_architecture" "src.core.cognitive_loop"
    "src.core.counterfactual" "src.core.behavior_compliance"
    "src.core.ebbinghaus" "src.core.predictive_context"
)
for mod in "${MODULES[@]}"; do
    if [ "$DRY_RUN" = false ]; then
        python3 -c "import $mod" 2>/dev/null && echo "  ✅ $mod" || echo "  ❌ $mod"
    else
        echo "  ✅ $mod (dry-run)"
    fi
done

# ── 4. macOS专有功能验证 ──
echo ""
echo "【4/8】macOS专有功能"
echo "  - screencapture (截图): $(which screencapture 2>/dev/null || echo 'not found')"
echo "  - osascript (AppleScript): $(which osascript 2>/dev/null || echo 'not found')"
echo "  - terminal-notifier: $(which terminal-notifier 2>/dev/null || echo 'not found')"
echo "  - Darwin platform detect: $(python3 -c 'import sys; print(sys.platform)' 2>/dev/null || echo 'unknown')"

# ── 5. 安装脚本验证 ──
echo ""
echo "【5/8】安装脚本"
if [ -f "install.sh" ]; then
    echo "  ✅ install.sh 存在"
    if [ "$DRY_RUN" = false ]; then
        bash -n install.sh 2>/dev/null && echo "  ✅ install.sh 语法正确" || echo "  ❌ install.sh 语法错误"
    fi
else
    echo "  ❌ install.sh 不存在"
fi

# ── 6. 构建脚本 ──
echo ""
echo "【6/8】macOS构建"
if [ -f "scripts/build-mac.sh" ]; then
    echo "  ✅ build-mac.sh 存在"
    if [ "$DRY_RUN" = false ]; then
        bash -n scripts/build-mac.sh 2>/dev/null && echo "  ✅ build-mac.sh 语法正确" || echo "  ❌ build-mac.sh 语法错误"
    fi
else
    echo "  ❌ build-mac.sh 不存在"
fi

# ── 7. 跨平台兼容检查 ──
echo ""
echo "【7/8】跨平台兼容"
DARWIN_REFS=$(grep -rn 'Darwin\|darwin\|macOS\|mac_os\|screencapture\|osascript' src/ --include='*.py' | wc -l)
echo "  macOS代码引用: $DARWIN_REFS 处"
PLATFORM_CHECKS=$(grep -rn 'platform.system\|sys.platform' src/ --include='*.py' | wc -l)
echo "  平台检测代码: $PLATFORM_CHECKS 处"

# ── 8. 单元测试 ──
echo ""
echo "【8/8】测试"
if [ "$DRY_RUN" = false ]; then
    echo "  运行核心测试..."
    python3 -m pytest tests/ -q -k 'not e2e' --ignore=tests/test_v22_features.py -x --tb=no 2>/dev/null | tail -3 || echo "  ⚠️ 测试执行异常"
else
    echo "  测试目录存在: $([ -d tests ] && echo '✅' || echo '❌')"
    echo "  测试文件数: $(find tests -name '*.py' | wc -l)"
fi

echo ""
echo "═══════════════════════════════════════"
echo " macOS 兼容性检查完成"
echo "═══════════════════════════════════════"
