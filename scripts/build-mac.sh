#!/bin/bash
# meshctx macOS Build Script
# Called by .github/workflows/build-macos.yml (macOS runner only)
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== meshctx macOS Build ==="
echo "Python: $(python3 --version)"
echo "PyInstaller: $(pyinstaller --version)"

# Ensure .icns icon exists for macOS .app bundle
if [ ! -f logo.icns ]; then
    echo "WARN: logo.icns not found, attempting conversion from logo.png..."
    python3 -c "
from PIL import Image
img = Image.open('logo.png')
img.save('logo.icns', format='ICNS', sizes=[16,32,64,128,256,512])
print('logo.icns created successfully')
" 2>/dev/null || echo "WARN: icon conversion failed, continuing..."
fi
ls -lh logo.icns 2>/dev/null || echo "WARN: no icon file found"

# Clean previous builds
rm -rf build dist

# Run PyInstaller with the multi-platform spec
pyinstaller --clean meshctx_desktop.spec

echo "=== Build Complete ==="

# Show results
if [ -d dist/meshctx-desktop.app ]; then
  echo "OK: dist/meshctx-desktop.app"
  ls -lh dist/meshctx-desktop.app/Contents/MacOS/meshctx-desktop 2>/dev/null || true
elif [ -f dist/meshctx-desktop ]; then
  echo "OK: dist/meshctx-desktop (binary)"
else
  echo "WARN: unexpected build output"
  ls -lh dist/
fi
