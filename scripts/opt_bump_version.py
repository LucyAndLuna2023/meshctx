# -*- coding: utf-8 -*-
"""通用版本资产同步: old_ver → new_ver (G10 全资产, 字节安全, 幂等)。

覆盖: src/__init__.py · src/core/__init__.py · package.json · version_info.txt
(含 filevers 元组) · meshctx_desktop.py · meshctx_setup.nsi · meshctx_desktop.spec
· install.sh (+ docs/install.sh 字节级同步)。

用法: python scripts/opt_bump_version.py 3.129.0 3.130.0
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

OLD, NEW = sys.argv[1], sys.argv[2]
assert OLD != NEW, "old == new"

OLD_B, NEW_B = OLD.encode(), NEW.encode()
MAJOR, MINOR, PATCH = (int(x) for x in NEW.split("."))
OM, OMm, Op = (int(x) for x in OLD.split("."))
OLD_TUP = f"{OM}, {OMm}, {Op}, 0".encode()
NEW_TUP = f"{MAJOR}, {MINOR}, {PATCH}, 0".encode()

TEXT_ASSETS = [
    "build.bat",
    "install.bat",
    "install-edition.bat",
    "docs/install.bat",
    "docs/install-edition.bat",
    "install-mac.sh",
    "docs/install-mac.sh",
    "install-edition.sh",
    "docs/install-edition.sh",
    "src/__init__.py",
    "src/core/__init__.py",
    "package.json",
    "version_info.txt",
    "meshctx_desktop.py",
    "meshctx_setup.nsi",
    "meshctx_desktop.spec",
    "install.sh",
]

# 定向模式资产: 只替换精确模式 (含历史注释的文件不可盲替换)
PATTERN_ASSETS = [
    ("src/main.py",                  'version="{old}"',        'version="{new}"'),   # M: FastAPI version= (002codex P2)
    ("tools/meshctx_support_bot.py", 'VERSION = "v{old}"',     'VERSION = "v{new}"'), # N: support bot
]
for rel, pat_old, pat_new in PATTERN_ASSETS:
    p2 = ROOT / rel
    raw = p2.read_bytes()
    po = pat_old.format(old=OLD, new=NEW).encode()
    pn = pat_new.format(old=OLD, new=NEW).encode()
    if po not in raw:
        print(f"[skip   ] {rel} (无定向模式 {po.decode()})")
        continue
    p2.write_bytes(raw.replace(po, pn))
    changed.append(rel)

changed = []
for rel in TEXT_ASSETS:
    p = ROOT / rel
    raw = p.read_bytes()
    n = raw.count(OLD_B)
    if not n:
        print(f"[skip   ] {rel} (无 {OLD})")
        continue
    raw = raw.replace(OLD_B, NEW_B)
    if OLD_TUP in raw:
        raw = raw.replace(OLD_TUP, NEW_TUP)
    p.write_bytes(raw)
    changed.append(rel)
    print(f"[bumped ] {rel} ({n} 处)")

src_sh, docs_sh = ROOT / "install.sh", ROOT / "docs" / "install.sh"
if src_sh.read_bytes() != docs_sh.read_bytes():
    docs_sh.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src_sh, docs_sh)
    print("[synced ] docs/install.sh <- install.sh")
else:
    print("[ok     ] docs/install.sh (已一致)")

print(f"\nDONE: {OLD} → {NEW}, {len(changed)} 资产更新")
