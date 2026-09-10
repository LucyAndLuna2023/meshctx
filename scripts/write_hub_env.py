#!/usr/bin/env python3
"""写入 ~/.meshctx/hub_env.json (0600) — hub 凭据轮换后各机器注入点 (P0 运维配套)。

用法: python scripts/write_hub_env.py <host> <port> <password>
不打印密码; 文件权限强制 0600; 已存在时提示先备份。
"""
import json, os, stat, sys
from pathlib import Path

if len(sys.argv) != 4:
    print(__doc__); sys.exit(2)
host, port, password = sys.argv[1], sys.argv[2], sys.argv[3]
d = Path(os.path.expanduser("~/.meshctx")); d.mkdir(parents=True, exist_ok=True)
p = d / "hub_env.json"
if p.exists():
    print(f"[注意] 覆盖已存在文件 {p} (旧值将被替换)")
p.write_text(json.dumps({"host": host, "port": int(port), "password": password},
                        ensure_ascii=False), encoding="utf-8")
os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)  # 0600
mode = oct(p.stat().st_mode & 0o777)
print(f"[ok] {p} 已写入 (mode={mode}, host={host}, port={port}, password=***)")
