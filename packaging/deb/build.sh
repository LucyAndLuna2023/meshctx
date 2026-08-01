#!/bin/bash
# Build .deb package for meshctx
# VERSION: tag (v3.116.0) 时取 tag；main 分支构建时回退读 version_info.txt
VERSION="${GITHUB_REF_NAME#v}"
if [[ ! "${VERSION}" =~ ^[0-9] ]]; then
  # 非 tag (如 main 分支 push) — 从 version_info.txt 提取版本号
  VERSION=$(grep -oE "filevers=\([0-9, ]+\)" version_info.txt | head -1 | grep -oE "[0-9]+" | paste -sd. -)
fi
echo "Building meshctx version: ${VERSION}"
DEB_ROOT="meshctx-deb"

mkdir -p "${DEB_ROOT}/DEBIAN"
mkdir -p "${DEB_ROOT}/opt/meshctx"
mkdir -p "${DEB_ROOT}/etc/systemd/system"
mkdir -p "${DEB_ROOT}/usr/local/bin"

# Copy source files
cp -r src "${DEB_ROOT}/opt/meshctx/"
cp -r plugins "${DEB_ROOT}/opt/meshctx/" 2>/dev/null || true
cp -r docs "${DEB_ROOT}/opt/meshctx/"
cp meshctx.yaml "${DEB_ROOT}/opt/meshctx/"
cp requirements.txt "${DEB_ROOT}/opt/meshctx/" 2>/dev/null || true

# Launcher script
cat > "${DEB_ROOT}/usr/local/bin/meshctx" << 'EOF'
#!/bin/bash
cd /opt/meshctx
exec python3 -m uvicorn src.main:app --host 0.0.0.0 --port 3000 "$@"
EOF
chmod 755 "${DEB_ROOT}/usr/local/bin/meshctx"

# Systemd service
cat > "${DEB_ROOT}/etc/systemd/system/meshctx.service" << 'EOF'
[Unit]
Description=MeshCtx AI Agent
After=network.target

[Service]
Type=simple
User=meshctx
WorkingDirectory=/opt/meshctx
ExecStart=/usr/local/bin/meshctx
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Control file
cat > "${DEB_ROOT}/DEBIAN/control" << ENDCTL
Package: meshctx
Version: ${VERSION}
Section: utils
Priority: optional
Architecture: all
Depends: python3, python3-pip
Maintainer: MeshCtx <jason.liu@meshctx.com>
Description: meshctx - self-evolving AI agent
 13 brain regions, 100+ models, 28 providers.
ENDCTL

# Post-install / pre-remove
cp packaging/deb/postinst "${DEB_ROOT}/DEBIAN/postinst"
chmod 755 "${DEB_ROOT}/DEBIAN/postinst"

cat > "${DEB_ROOT}/DEBIAN/prerm" << 'EOF'
#!/bin/bash
systemctl stop meshctx 2>/dev/null || true
systemctl disable meshctx 2>/dev/null || true
EOF
chmod 755 "${DEB_ROOT}/DEBIAN/prerm"

# Build
dpkg-deb --root-owner-group --build "${DEB_ROOT}" "meshctx_${VERSION}_all.deb"
ls -lh meshctx_*.deb
