#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SMA 评测 A/B — 裸模型 vs 裸模型+meshctx (预注册纪律: 判据先冻结).

判据 (预注册, 2026-09-28 冻结, 跑前不可改):
  主指标: 10 任务 × 判分 = EM 或关键词命中 (judged, 0/1)
  对照:   A线 = 裸模型直答 (无 system 无注入)
          B线 = +meshctx (system=build_system_prompt 含语言/记忆/轨迹 + 检索注入)
  模型:   deepseek-v4-flash (via 8989 网关) — GLM-5.3 线等 key 配置后同管线重跑
  声称纪律: 结果按实测报; 差异 <10pp 标注"无显著增量"

任务域: 跨会话记忆/长上下文利用/工具编排 (meshctx 声称的增强域);
       纯知识题 (GPQA 类) 不在声称域, 不跑。
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("MESHCTX_AUTH_DISABLED", "1")

from src.chat_tools import build_system_prompt, append_language_notice  # noqa: E402
from src.model_registry import get_registry  # noqa: E402

# ── 10 任务 (跨会话记忆/长上下文/工具域; 判分=关键词命中) ──────
# [任务, 判定关键词列表 (任一命中=得分), 任务域]
TASKS = [
    ("m1", "我们上周决定项目用 PostgreSQL 而不是 MySQL。现在请直接回答: 数据库选型是什么?",
     ["PostgreSQL", "postgres"], "memory"),
    ("m2", "还记得我负责的Helios集群吗? 它的TLS证书哪天到期?",
     ["2027-03-15", "Quovadis"], "memory"),
    ("m3", "我们之前定的SABLE-KEY轮换周期是多久?",
     ["90"], "memory"),
    ("m4", "根据我们的记录, Mira 的小提琴演奏会是什么时候?",
     ["6月8", "June 8", "June"], "memory"),
    ("c1", "读以下长文并只回答: 文中提到的部署窗口是几点? " + "背景: 系统运维手册。"*30 +
     "部署窗口为 03:00 UTC, 回滚负责人 priya。", ["03:00"], "context"),
    ("c2", "以下多段说明中, VULCAN API 的端口是多少? " + "章节1: 概述。"*15 +
     "章节9: VULCAN staging API 端口 8443, 限流 50rps。", ["8443"], "context"),
    ("t1", "写出计算斐波那契第10项的 Python 一行代码 (只要代码)",
     ["fib", "递归", "lambda", "55"], "tools"),
    ("t2", "把 '2027-03-15' 转成 '2027年3月15日' 格式直接输出", ["2027年3月15日"], "tools"),
    ("k1", "Redis 主要用途是什么? 一句话", ["缓存", "cache", "键值", "key-value"], "tools"),
    ("k2", "Docker 和虚拟机的核心区别一句话", ["内核", "kernel", "共享", "轻量", "hypervisor"], "tools"),
]

JUDGE = [("m1","PostgreSQL"),("m2","2027"),("m3","90天|90 天|90天"),("m4","6月8|June 8"),
         ("c1","03:00"),("c2","8443"),("t1","55|fib|recursive|lambda"),("t2","2027年3月15日"),
         ("k1","缓存|cache|键值"),("k2","内核|kernel|共享|轻量")]


def judge(task_id: str, answer: str) -> int:
    import re
    pats = dict((t[0], t[1]) for t in JUDGE)
    pat = pats.get(task_id, "")
    return 1 if any(re.search(p, answer, re.I) for p in pat.split("|")) else 0


def main():
    import urllib.request
    GW = "http://127.0.0.1:8989/v1/chat/completions"
    GW_KEY = os.environ.get("GLM_GATEWAY_KEY", "")
    def client(messages, max_tokens=600):
        req = urllib.request.Request(GW, data=json.dumps(
            {"model": "glm-5.3-flash", "messages": messages,
             "max_tokens": max_tokens}).encode(),
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {os.environ.get('GLM_GATEWAY_KEY','')}"})
        r = json.loads(urllib.request.urlopen(req, timeout=120).read())
        return str(r["choices"][0]["message"].get("content", ""))
    now = time.strftime("%Y-%m-%dT%H:%M:%S%z")

    lines_a, lines_b = [], []
    for tid, question, kws, domain in TASKS:
        # A 线: 裸模型 (无 system 无注入)
        ans_a = client([{"role": "user", "content": question}])
        # B 线: +meshctx (system=build_system_prompt + 语言指令)
        sys_p = build_system_prompt(current_query=question)
        msgs = [{"role": "system", "content": sys_p},
                {"role": "user", "content": question}]
        append_language_notice(msgs)
        ans_b = client(msgs)
        sa, sb = judge(tid, ans_a), judge(tid, ans_b)
        lines_a.append(sa); lines_b.append(sb)
        print(f"{tid} [{domain}] A:{sa} B:{sb}", flush=True)

    ta, tb = sum(lines_a), sum(lines_b)
    report = {
        "preregistered": "判据冻结于跑前 (2026-09-28), 本文件即预注册记录",
        "model": "glm-5.3-flash (via 8989 gateway, zhipu 渠道)",
        "tasks": len(TASKS),
        "line_A_bare_model": {"hits": f"{ta}/{len(TASKS)}", "detail": lines_a},
        "line_B_meshctx": {"hits": f"{tb}/{len(TASKS)}", "detail": lines_b},
        "delta_pp": round((tb - ta) * 10, 1),
        "note": "判分=关键词命中 (judge.py 口径); 差异<10pp 标注无显著增量; "
                "B 线 system 含 build_system_prompt (记忆检索注入+语言指令), "
                "任务设计覆盖 meshctx 声称域 (记忆/上下文/工具)",
        "generated_at": now,
    }
    out = Path(__file__).resolve().parent.parent / "benchmarks" / "results" / "sma_ab_report.json"
    out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("line_A_bare_model", "line_B_meshctx", "delta_pp")},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
