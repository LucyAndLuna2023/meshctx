# -*- coding: utf-8 -*-
"""v3.129.0 优化补丁 (字节安全版) — 修复 PowerShell GBK 事故后的重做。

全部以 bytes 读写, 不经过任何 locale 编码转换:
  A. 剥离 src/__init__.py / package.json / version_info.txt 的 UTF-8 BOM
  B. src/core/__init__.py: __version__ 3.128.0 → 3.129.0
  C. src/main.py: datetime.utcnow() 弃用 API → timezone-aware (输出格式不变)
幂等: 已应用过的补丁自动跳过。
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def rw(path: Path, transform):
    raw = path.read_bytes()
    new = transform(raw)
    if new != raw:
        path.write_bytes(new)
        print(f"[patched] {path.relative_to(ROOT)}")
    else:
        print(f"[ok/skip ] {path.relative_to(ROOT)}")


# A. BOM 剥离
for rel in ["src/__init__.py", "package.json", "version_info.txt"]:
    p = ROOT / rel
    raw = p.read_bytes()
    if raw[:3] == b"\xef\xbb\xbf":
        p.write_bytes(raw[3:])
        print(f"[de-bom  ] {rel}")
    else:
        print(f"[ok/skip ] {rel} (no BOM)")

# B. core/__init__.py 版本号
rw(ROOT / "src/core/__init__.py",
   lambda b: b.replace(b'__version__ = "3.128.0"', b'__version__ = "3.129.0"'))

# C. main.py utcnow → timezone-aware (输出格式保持 "...Z")
rw(ROOT / "src/main.py",
   lambda b: b.replace(
       b'datetime.datetime.utcnow().isoformat() + "Z"',
       b'datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")'))
