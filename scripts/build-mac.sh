#!/bin/bash
# meshctx macOS Build Script
# Called by .github/workflows/build-macos.yml (macOS runner only)
set -euo pipefail
cd "$(dirname "$0")/.."

echo "=== meshctx macOS Build ==="
echo "Python: $(python3 --version)"
echo "PyInstaller: $(pyinstaller --version)"

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
