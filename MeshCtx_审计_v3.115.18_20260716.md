# MeshCtx v3.115.18 审计报告
> 审计方: 004qa | 时间: 2026-07-16 | 审计对象: UPDATE_PLAN_v3.115.18_to_17_brain.md

## 一、进步确认

| 指标 | v6(13脑区 Jul4) | v9(17脑区 Jul16) | 变化 |
|------|:---:|:---:|:---:|
| 综合评分 | 39.0% | 63.2% | +24.2pp |
| 通过指标 | 11/24 | 29/42 | — |

关键修复确认:
- ACC 50%→100% (拼写bug ernn→errn修复)
- Mirror 20%→100% (意图推理修复)
- STDP 0%→100% (权重更新修复)
- Thalamus 0%→70% (门控self-lock修复)
- Amygdala FPR 100%→23% (特异性大幅改善)

## 二、P0 严重问题

### 1. UPDATE_PLAN数据自相矛盾
- L35: Hippocampus标20%，实际基准报告=60%
- L38: Thalamus标13%，实际基准报告=70%
- L92-93: P3改进清单沿用旧数据
- L122: meshctx自己发现了矛盾但未修正
→ **根因**: v6旧数据混入UPDATE_PLAN，需全部替换为v9真实数据。

### 2. 对外宣称严重过期
| 位置 | 宣称 | 实际 |
|------|------|------|
| meshctx.com <title> | 13-Brain-Region | 17 |
| README.md L4 | 9脑区·9模块 | 17脑区·200+模块 |
| README badge | brain_regions-9 | 17 |
| README 版本号 | v3.115.15 | v3.115.18 |
| README badge | tests-130 | 1279 |

→ 网站13、README9、代码17 — 三个版本各说各的。

## 三、P1 新脑区警告

| 脑区 | 评分 | 核心问题 |
|------|:--:|------|
| Brainstem | 25% | Homeostasis=0, ArousalCtrl=0 — 完全不工作 |
| NAcc | 35% | PE_Converge=2%, Want/Liking=0.04 — TD不收敛 |
| Cerebellum | 33% | InitMSE=18.6→FinalMSE=17.0 — 几乎没学习 |

→ 以"17脑区"名义发布但3个几乎不工作，建议标注experimental。

## 四、P1 基准方法论
- Hippocampus LDI=0, PSI=0 — 文本精确匹配非语义匹配(人类LDI 0.15-0.35)
- Emotion ConsolRange=0 — 情绪巩固无分化
- PFC WM_Recall=0.1483 — 工作记忆仅14.8%

## 五、P2评估

更新计划结构合理(P0→P1→P2→P3)，执行顺序清晰。
风险: JS i18n翻译需同步更新sb10-sb13新卡片。

## 六、修复建议（按优先级）
1. UPDATE_PLAN更正所有v6旧数据→v9
2. meshctx.com 13→17 (P0-1~P0-10)
3. README.md 9→17 + v3.115.15→v3.115.18 + tests-130→1279
4. Brainstem/NAcc/Cerebellum标注"experimental/beta"
5. Hippocampus LDI/PSI改用语义匹配

---
*审计方: 004qa | 报告同时存于 Desktop + meshctx-public/ 仓库*
