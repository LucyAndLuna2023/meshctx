# -*- coding: utf-8 -*-
"""交接通知 → 004deepseek: zcode 夜间+晨间工作完整交付。项目 meshctx。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cluster"))
sys.path.insert(0, str(ROOT))
import cluster_comm_v6 as v6  # noqa: E402

MSG = """[交接通知 · zcode@004 → 004deepseek] (项目 meshctx)

我方按用户指令完成全部优化工作, 现交接给你接续。完整交接文档:
交付目录 HANDOFF_004deepseek_20260911.md

■ 已完成:
- v3.131.2 已发布 (tag @f13fb10f, CI 4/4, 24 资产, meshctx.com 已切)
- 模型中心 Model Hub + 实时模型列表 + 智谱双端点 + 错误中文提示
- Linux/Mac 免登录 (回环加固) + UI no-cache (升级免 Ctrl+F5)
- 自进化闭环 v1 (self_evolution.py): record→reflect→inject→reinforce,
  E2E 实测通过; code_run + chat 结果自动入经验层
- 集群通讯 v6 (cluster_comm_v6.py): zcode@004/meshctx, 项目隔离, 零凭据
- 源码零凭据 + provider_config 原子写 0600 + hub 凭据轮换手册
- /ui/models 收口到 Model Hub; 全量回归 3883/0/66 (工作区)

■ 待你接续 (按优先级):
1. 自进化 Phase-1: LLM 反思改写 (粗规则→chat_tools 模型精炼)
2. 11 语言 Model Hub 新增 key 补翻
3. hub 凭据轮换 (需 001/003 admin)
4. 版本 bump + tag 下一版 → CI → Release
5. chat 结果经验蒸馏质量验证 (跑 3 天真实数据)

■ 详细文档:
- 交接: HANDOFF_004deepseek_20260911.md
- 审计: OPTIMIZATION_REPORT_v3.129.0.md §1-13
- 设计: docs/SELF_EVOLUTION_DESIGN.md
- 集群: cluster/CLUSTER_V6_MESHCTX.md
- 打磨: docs/PRODUCT_POLISH_PLAN.md

zcode@004 · hub:inbox:004:zcode:meshctx"""

r = v6.get_redis()
out = v6.send_dm("004", MSG, from_profile=v6.AGENT, to_profile="deepseek:meshctx", r=r)
print("→ 004/deepseek:", out if isinstance(out, str) else json.dumps(out, ensure_ascii=False))
print("journal:", json.dumps(v6.journal_verify(), ensure_ascii=False))
