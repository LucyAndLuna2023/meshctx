#!/bin/bash
set -e
mkdir -p /opt/meshctx/static/dl/v1.6.0/
cd /opt/meshctx/static/dl/v1.6.0/
# Download 3 artifacts from GitHub Releases
echo "Downloading meshctx.exe..."
curl -L --retry 5 --retry-delay 30 --connect-timeout 60 -o meshctx.exe \
  "https://github.com/LucyAndLuna2023/meshctx/releases/download/v1.6.0/meshctx.exe"
echo "exe: $(ls -lh meshctx.exe | awk '{print $5}')"

echo "Downloading meshctx-setup.exe..."
curl -L --retry 5 --retry-delay 30 --connect-timeout 60 -o meshctx-setup.exe \
  "https://github.com/LucyAndLuna2023/meshctx/releases/download/v1.6.0/meshctx-setup.exe"
echo "setup: $(ls -lh meshctx-setup.exe | awk '{print $5}')"

echo "Downloading meshctx-portable.zip..."
curl -L --retry 5 --retry-delay 30 --connect-timeout 60 -o meshctx-portable.zip \
  "https://github.com/LucyAndLuna2023/meshctx/releases/download/v1.6.0/meshctx-portable.zip"
echo "zip: $(ls -lh meshctx-portable.zip | awk '{print $5}')"

sha256sum meshctx.exe > sha256.txt
echo "== ALL DONE =="
ls -lh
