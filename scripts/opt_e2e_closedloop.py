# -*- coding: utf-8 -*-
"""端到端闭环验证 (真实 HTTP): record×20 → 自动 reflect → insights 非空 → system prompt 注入。"""
import sys

sys.path.insert(0, ".")
from fastapi.testclient import TestClient  # noqa: E402
from src.main import app  # noqa: E402

c = TestClient(app)

print("== ① 经 API 记录 20 条经验 (10 python 成功 / 10 bash 失败) ==")
for i in range(10):
    assert c.post("/api/evolution/record", json={
        "task_type": "e2e_probe", "strategy": "python", "outcome": True}).json()["status"] == "ok"
    c.post("/api/evolution/record", json={
        "task_type": "e2e_probe", "strategy": "bash", "outcome": False})

print("== ② 自动 reflect 应已触发 (无手动调用) ==")
st = c.get("/api/evolution/stats").json()
print("stats:", st)
assert st["insights"] >= 1, "自动反思未触发!"
assert st["chain_verified"] is True

print("== ③ /api/evolution/insights 应返回洞见 ==")
ins = c.get("/api/evolution/insights?task_type=e2e_probe").json()["insights"]
assert ins and "python" in ins[0], ins
for s in ins:
    print("  ·", s)

print("== ④ build_system_prompt 注入验证 ==")
from src.chat_tools import build_system_prompt  # noqa: E402
sp = build_system_prompt()
assert "e2e_probe" in sp and "优先采用策略" in sp, "系统提示词未注入洞见!"
print("system prompt 注入 ✓ (洞见已进入 SYSTEM_PROMPT 记忆段)")

print("\nE2E_CLOSED_LOOP_PASS — 自学习闭环无需人工干预自转 ✓")
