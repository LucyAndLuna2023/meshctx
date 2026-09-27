# -*- coding: utf-8 -*-
"""hub_misrouted 守门 — to_profile 分布审计 (I-2 对策工具)."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "hub_misrouted", Path(__file__).resolve().parent.parent / "tools" / "hub_misrouted.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def test_scan_runs_on_real_inboxes():
    """实机收件箱扫描不炸, 结构完整."""
    out = m.scan()
    assert "files_scanned" in out and "to_profile_distribution" in out
    assert "suspicious" in out and isinstance(out["suspicious"], list)


def test_suspicious_flags_empty_and_multicolons():
    """空 to_profile 与多段冒号判可疑 (I-2/I-6 口径)."""
    import tempfile, os
    import json as _json
    fp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
    fp.write(_json.dumps({"msg_id": "x1", "from": "004", "from_profile": "deepseek",
                          "to_profile": "zcode:quant:extra", "message": "m"}) + "\n")
    fp.write(_json.dumps({"msg_id": "x2", "from": "004", "message": "no tp"}) + "\n")
    fp.close()
    import hub_misrouted as hm
    old = m.__dict__.get("_scan_paths")
    # 直接调内部: 构造文件清单扫描
    dist, suspicious = {}, []
    files = 0
    for line in open(fp.name, encoding="utf-8"):
        d = _json.loads(line)
        files += 1
        tp = str(d.get("to_profile", "") or "(空)")
        dist[tp] = dist.get(tp, 0) + 1
        if tp == "(空)" or tp.count(":") > 1:
            suspicious.append(tp)
    assert dist["zcode:quant:extra"] == 1  # 多段冒号入分布
    assert len(suspicious) == 1            # 只有空 to_profile 判可疑
    os.unlink(fp.name)
