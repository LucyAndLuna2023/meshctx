# -*- coding: utf-8 -*-
"""优化任务派发 → 002zcode (用户指令: 本机 CPU/内存太高, 转交 002 执行夜间优化)。项目 meshctx。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "cluster"))
sys.path.insert(0, str(ROOT))
import cluster_comm_v6 as v6  # noqa: E402

MSG = """[任务转交 · meshctx 夜间优化 → 002zcode] 发起: 用户经 zcode@004

■ 背景: 004 本机 CPU/内存占用太高, 用户要求把 meshctx 夜间优化任务转交给你执行。

■ 你的任务 (每晚 23:00→次日 09:00, token 免费):
  1. 拉取主线最新代码: git pull origin main (HEAD 应 ≥ d3fe6dd3)
  2. 全方位优化 meshctx (按 DeepSeek/ZCode 标准):
     a. 自进化闭环 Phase-1: LLM 反思改写 (接 chat_tools 模型调用, 粗规则→精炼洞见)
     b. UI/UX 打磨: Model Hub Wizard 引导, chat tool_result 渲染, 错误提示优化
     c. i18n: 11 语言 Model Hub 新增 key 补翻 (上次扫描 14 缺)
     d. 性能: API 延迟 (500 猎捕器/scripts/opt_api_benchmark.py 可复用)
     e. 测试: 边缘用例 + 集成测试
  3. 每项改动必跑门禁 (tests/test_cluster_comm_v6.py 等 4 文件)
  4. 完成后 commit + push origin main + 跑全量回归
  5. 结果发回: hub:inbox:004:zcode:meshctx

■ 交付物 (已在 main, 你在此基础上继续):
  - src/core/self_evolution.py: 自进化闭环 v1 (统计蒸馏+LLM精炼+FSRS+哈希链)
  - cluster/cluster_comm_v6.py: 集群通讯 (零凭据, env→hub_env.json 注入)
  - templates/setup.html: Model Hub (Key 自动识别厂商/自动测活/切换持久化)
  - templates/chat.html: 错误中文映射/toast/evolution面板
  - tests/: 78+ 新用例
  - 全量: 3899 passed / 0 failed / 64 skipped (WSL 独立复跑)

■ 注意:
  - 源码零凭据 (hub 密码经 env/~/.meshctx/hub_env.json 注入, 不入代码)
  - 本仓 src/core/*.py 为 stub, 安装时由闭源覆盖
  - chat 结果已入经验层 (generate() finally 块)
  - provider test 结果已入经验层 (finally 块)

■ 文档: OPTIMIZATION_REPORT_v3.129.0.md §1-13 / docs/SELF_EVOLUTION_DESIGN.md
         cluster/CLUSTER_V6_MESHCTX.md / docs/PRODUCT_POLISH_PLAN.md

zcode@004 · hub:inbox:004:zcode:meshctx"""

TARGETS = [("002", "zcode")]


def main():
    r = v6.get_redis()
    ok_all = True
    for mid, profile in TARGETS:
        # 002: 单段 to_profile + project_id (约定形式)
        out = v6.send_dm(mid, MSG, from_profile=v6.AGENT, to_profile=profile,
                         project_id="meshctx", r=r)
        ok = isinstance(out, str) and out != "rejected"
        ok_all = ok_all and ok
        print(f"→ {mid}/{profile}: {'✓ msg_id=' + out if ok else '✗ ' + json.dumps(out, ensure_ascii=False)}")
    print("journal:", json.dumps(v6.journal_verify(), ensure_ascii=False))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
