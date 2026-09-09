# -*- coding: utf-8 -*-
"""G10 版本资产同步: 3.128.0 → 3.129.0 (tests/test_project_integrity.py 口径)。

字节安全 (bytes 读写), 幂等; install.sh 更新后整体复制到 docs/install.sh
(两者存在字节级一致性测试)。
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OLD, NEW = b"3.128.0", b"3.129.0"

ASSETS = [
    "meshctx_desktop.py",
    "meshctx_setup.nsi",
    "meshctx_desktop.spec",
    "install.sh",
]

for rel in ASSETS:
    p = ROOT / rel
    raw = p.read_bytes()
    if OLD in raw:
        p.write_bytes(raw.replace(OLD, NEW))
        print(f"[bumped ] {rel}")
    elif NEW in raw:
        print(f"[ok/skip] {rel} (already {NEW.decode()})")
    else:
        print(f"[WARN   ] {rel}: 版本串未找到!")

src_sh, docs_sh = ROOT / "install.sh", ROOT / "docs" / "install.sh"
if src_sh.read_bytes() != docs_sh.read_bytes():
    docs_sh.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src_sh, docs_sh)
    print("[synced ] docs/install.sh <- install.sh")
else:
    print("[ok/skip] docs/install.sh (identical)")
print("DONE")
