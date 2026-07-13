#!/bin/bash
# ═══════════════════════════════════════════════════════
# meshctx macOS DMG 打包脚本
# 用法: bash scripts/build-dmg.sh [version]
#   需要: Python 3.10+, PyInstaller, create-dmg (可选)
#   输出: dist/meshctx-{version}.dmg
# ═══════════════════════════════════════════════════════
set -euo pipefail
cd "$(dirname "$0")/.."

# ── 版本 ──
VERSION="${1:-3.115.15}"
APP_NAME="meshctx-desktop"
DMG_NAME="meshctx-${VERSION}"
BUNDLE_ID="com.meshctx.desktop"

echo "═══════════════════════════════════════"
echo " meshctx DMG Builder v1.0"
echo " Version: ${VERSION}"
echo "═══════════════════════════════════════"

# ── macOS 检测 ──
if [[ "$(uname)" != "Darwin" ]]; then
    echo "✗ 此脚本仅支持 macOS"
    echo "  Linux/WSL 请使用 PyInstaller 交叉编译"
    exit 1
fi

# ── Python 检查 ──
PYTHON=""
for p in python3.12 python3.11 python3.10 python3; do
    if command -v "$p" >/dev/null 2>&1; then
        ver=$($p --version 2>&1 | grep -oE '[0-9]+\.[0-9]+' | head -1)
        major=$(echo "$ver" | cut -d. -f1)
        minor=$(echo "$ver" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ] 2>/dev/null; then
            PYTHON="$p"
            break
        fi
    fi
done

if [ -z "${PYTHON}" ]; then
    echo "✗ 需要 Python 3.10+"
    echo "  brew install python@3.12"
    exit 1
fi

echo "Python: $(${PYTHON} --version)"

# ── 依赖安装 ──
echo ""
echo "[1/5] 检查构建依赖..."

# PyInstaller
if ! ${PYTHON} -m PyInstaller --version >/dev/null 2>&1; then
    echo "  → 安装 PyInstaller..."
    ${PYTHON} -m pip install pyinstaller --quiet
fi
echo "  ✓ PyInstaller: $(${PYTHON} -m PyInstaller --version)"

# create-dmg (可选，用于生成美观的 DMG)
HAVE_DMGTOOL=false
if command -v create-dmg >/dev/null 2>&1; then
    HAVE_DMGTOOL=true
    echo "  ✓ create-dmg: $(create-dmg --version 2>&1 | head -1)"
else
    echo "  ⚠ create-dmg 未安装（DMG 将用 hdiutil 基础打包）"
    echo "    安装: brew install create-dmg"
fi

# ── 图标准备 ──
echo ""
echo "[2/5] 准备图标..."

if [ ! -f "logo.icns" ]; then
    if [ -f "logo.png" ]; then
        echo "  → 从 logo.png 生成 logo.icns..."
        # 创建临时 iconset
        ICONSET="logo.iconset"
        mkdir -p "${ICONSET}"

        # 使用 sips 生成各种尺寸 (macOS 自带)
        for size in 16 32 64 128 256 512; do
            sips -z $size $size logo.png --out "${ICONSET}/icon_${size}x${size}.png" >/dev/null 2>&1 || true
            double=$((size * 2))
            sips -z $double $double logo.png --out "${ICONSET}/icon_${size}x${size}@2x.png" >/dev/null 2>&1 || true
        done

        iconutil -c icns "${ICONSET}" -o logo.icns 2>/dev/null || {
            echo "  ⚠ iconutil 转换失败，使用 Python PIL 转换..."
            ${PYTHON} -c "
from PIL import Image
img = Image.open('logo.png')
img.save('logo.icns', format='ICNS')
print('logo.icns created via PIL')
" 2>/dev/null || echo "  ⚠ 图标生成失败，继续无图标构建"
        }
        rm -rf "${ICONSET}"
    else
        echo "  ⚠ logo.png 未找到，跳过图标"
    fi
fi

if [ -f "logo.icns" ]; then
    echo "  ✓ logo.icns: $(du -h logo.icns | cut -f1)"
fi

# ── PyInstaller 构建 ──
echo ""
echo "[3/5] PyInstaller 构建..."

# 清理旧构建
rm -rf build dist

# 确保依赖已安装
${PYTHON} -m pip install fastapi uvicorn pydantic jinja2 httpx pyyaml numpy openai aiofiles packaging python-multipart aiohttp --quiet 2>/dev/null || true

# PyInstaller 打包
echo "  → 正在打包（可能需要几分钟）..."

${PYTHON} -m PyInstaller \
    --clean \
    --noconfirm \
    --name "${APP_NAME}" \
    --add-data "logo.png:." \
    --add-data "logo.icns:." \
    --add-data "templates:templates" \
    --add-data "static:static" \
    --hidden-import "fastapi" \
    --hidden-import "uvicorn" \
    --hidden-import "uvicorn.loops" \
    --hidden-import "uvicorn.loops.auto" \
    --hidden-import "uvicorn.protocols" \
    --hidden-import "uvicorn.protocols.http" \
    --hidden-import "uvicorn.protocols.http.auto" \
    --hidden-import "jinja2" \
    --hidden-import "pydantic" \
    --hidden-import "httpx" \
    --hidden-import "pyyaml" \
    --hidden-import "aiofiles" \
    --hidden-import "numpy" \
    --hidden-import "openai" \
    --hidden-import "packaging" \
    --hidden-import "aiohttp" \
    --windowed \
    --icon "logo.icns" \
    --osx-bundle-identifier "${BUNDLE_ID}" \
    src/main.py 2>&1 | tail -5

# 检查构建结果
if [ -d "dist/${APP_NAME}.app" ]; then
    echo "  ✓ .app 构建成功"
    ls -lh "dist/${APP_NAME}.app/Contents/MacOS/" | grep -v "^total"
elif [ -f "dist/${APP_NAME}/${APP_NAME}" ]; then
    echo "  ✓ 二进制构建成功"
    ls -lh "dist/${APP_NAME}/${APP_NAME}"
else
    echo "  ✗ 构建失败"
    echo "  尝试检查 dist/ 目录:"
    ls -la dist/ 2>/dev/null || echo "  (dist/ 不存在)"
    exit 1
fi

# ── DMG 打包 ──
echo ""
echo "[4/5] 创建 DMG..."

DMG_DIR="dist/dmg"
rm -rf "${DMG_DIR}"
mkdir -p "${DMG_DIR}"

# 复制 .app
if [ -d "dist/${APP_NAME}.app" ]; then
    cp -R "dist/${APP_NAME}.app" "${DMG_DIR}/"
elif [ -f "dist/${APP_NAME}/${APP_NAME}" ]; then
    # 创建 .app 骨架
    mkdir -p "${DMG_DIR}/${APP_NAME}.app/Contents/MacOS"
    mkdir -p "${DMG_DIR}/${APP_NAME}.app/Contents/Resources"
    cp "dist/${APP_NAME}/${APP_NAME}" "${DMG_DIR}/${APP_NAME}.app/Contents/MacOS/"
    if [ -f "logo.icns" ]; then
        cp "logo.icns" "${DMG_DIR}/${APP_NAME}.app/Contents/Resources/"
    fi
fi

# 创建 Applications 快捷方式
ln -sf /Applications "${DMG_DIR}/Applications"

# 生成 DMG
DMG_PATH="dist/${DMG_NAME}.dmg"
rm -f "${DMG_PATH}"

if [ "${HAVE_DMGTOOL}" = true ]; then
    # 使用 create-dmg（美观）
    echo "  → 使用 create-dmg..."
    create-dmg \
        --volname "meshctx Installer" \
        --volicon "logo.icns" \
        --window-pos 200 120 \
        --window-size 800 400 \
        --icon-size 100 \
        --icon "${APP_NAME}.app" 200 190 \
        --hide-extension "${APP_NAME}.app" \
        --app-drop-link 600 185 \
        "${DMG_PATH}" \
        "${DMG_DIR}/" 2>&1 | tail -3
else
    # 使用 hdiutil（基础）
    echo "  → 使用 hdiutil..."
    hdiutil create \
        -volname "meshctx Installer" \
        -srcfolder "${DMG_DIR}" \
        -ov -format UDZO \
        "${DMG_PATH}" 2>&1 | tail -3
fi

if [ -f "${DMG_PATH}" ]; then
    DMG_SIZE=$(du -h "${DMG_PATH}" | cut -f1)
    echo "  ✓ DMG 创建成功: ${DMG_PATH} (${DMG_SIZE})"
else
    echo "  ✗ DMG 创建失败"
    exit 1
fi

# ── 清理 ──
echo ""
echo "[5/5] 清理..."
rm -rf "${DMG_DIR}"

# ── 完成 ──
echo ""
echo "═══════════════════════════════════════"
echo " ✅ 构建完成"
echo ""
echo "  DMG: dist/${DMG_NAME}.dmg"
echo "  App: dist/${APP_NAME}.app"
echo ""
echo "  上传到 GitHub Release:"
echo "    gh release upload v${VERSION} dist/${DMG_NAME}.dmg"
echo ""
echo "  本地安装测试:"
echo "    open dist/${DMG_NAME}.dmg"
echo "═══════════════════════════════════════"
