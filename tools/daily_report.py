#!/usr/bin/env python3
"""meshctx每日自动汇报 — 写入E盘 + 飞书推送(需webhook URL)"""
import os, sys, time, subprocess
from pathlib import Path
from datetime import datetime

REPORT_DIR = Path("E:/Meshctx/每日汇报") if os.name == 'nt' else Path("/mnt/e/Meshctx/每日汇报")
FEISHU_SECRET = "EUAN7gQ0xShrLeQiHenVXeYaVBNzHMsL"

def get_git_log():
    try:
        r = subprocess.run(["git", "log", "--oneline", "-10"], capture_output=True, text=True, cwd=Path(__file__).parent)
        return r.stdout.strip()
    except:
        return "(git unavailable)"

def get_test_results():
    try:
        r = subprocess.run(["python", "-m", "pytest", "tests/", "-q", "--tb=no"], 
                         capture_output=True, text=True, cwd=Path(__file__).parent, timeout=120)
        for line in r.stdout.split("\n") + r.stderr.split("\n"):
            if "passed" in line or "failed" in line:
                return line.strip()
    except:
        pass
    return "(tests not run)"

def main():
    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    git_log = get_git_log()
    test_result = get_test_results()
    
    report = f"""# MeshCtx 每日汇报 — {today}

## 状态
- 时间: {now}
- 测试: {test_result}

## 最近提交
{git_log}

## 备注
- 远程: 47.120.0.239:3001
- 主页: https://meshctx.com
- Release: https://github.com/LucyAndLuna2023/meshctx/releases/latest
"""
    
    # 写入E盘
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"{today}.md"
    report_path.write_text(report, encoding="utf-8")
    print(f"✅ 汇报已写入: {report_path}")
    
    # 飞书推送(如果webhook URL已配置)
    webhook_url = os.environ.get("FEISHU_WEBHOOK_URL", "")
    if webhook_url:
        _send_feishu(webhook_url, report)
    
    return report

def _send_feishu(url, text):
    import urllib.request, json
    payload = json.dumps({
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"content": "MeshCtx 每日汇报", "tag": "plain_text"}},
            "elements": [{"tag": "markdown", "content": text[:3000]}]
        }
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req)
    print("✅ 飞书已推送")

if __name__ == "__main__":
    print(main())
