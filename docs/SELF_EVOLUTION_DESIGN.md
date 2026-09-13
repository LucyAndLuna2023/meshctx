# meshctx 自学习/自优化架构设计 (Self-Evolution Loop v1)

> 作者: zcode@004 · 2026-09-10 夜间优化批
> 方法论来源: 2026 SOTA 调研 (来源清单见文末) × meshctx 现有模块审计
> Phase-0 实现: `src/core/self_evolution.py` (零 LLM 依赖, 离线可用)

---

## 1. SOTA 结论 (2026-09 调研)

学界已收敛的框架 (Gao et al. 2025, 被引 272; Ren et al. 2026):

| 维度 | 问题 | 主流答案 |
|---|---|---|
| **What** 演化什么 | 改哪一层 | ① 提示/策略 (最安全) ② 技能库 (可执行代码) ③ 模型权重 (最贵) |
| **When** 何时演化 | 触发时机 | 测试时即时 (TT-SI) / 任务后批量 / 周期性整理 |
| **How** 怎么演化 | 更新机制 | 反思蒸馏 (ExpeL) / 技能库 (Voyager) / 反思式提示演化 (GEPA) / RL (RAGEN) |

三大范式收敛为一个闭环: **执行 → 反思 → 记忆 → 技能/策略积累 → 检索注入下一次执行**。

关键实证:
- **GEPA** (arXiv:2507.19457): 反思式提示演化胜过 RL 高达 19%, 样本效率 35× —
  说明**不需要训练模型**, 从执行轨迹反思提炼即可获得大幅收益。
- **ExpeL** (AAAI'24): 从成功/失败轨迹蒸馏自然语言洞见, 零梯度更新即可学习。
- **Voyager**: 可执行技能库 + 嵌入检索 = 终身学习基座。
- **安全告诫** (多篇): 技能/洞见文件本质是持久化提示注入面 — 必须只信自己生成
  的经验, 带来源与完整性校验。

## 2. meshctx 现有资产审计 (哪些积木已有, 缺什么)

| 现有模块 | 状态 | 在闭环中的角色 |
|---|---|---|
| learn_loop / online_learning / error_learner | 已实现 | 经验记录 (分散, 未统一) |
| memory_hierarchy (FSRS) / memory_v2/v5 | 已实现 | 记忆层 (有遗忘曲线!可直接用于洞见保持度) |
| metacognition / feedback_loop | 已实现 | 反思 (入口未接执行轨迹) |
| prompt_optimizer / prompt_registry | 已实现 | 策略演化 (无效果归因) |
| web3_messaging (哈希链) / self_debug / code_reviewer | 已实现 | 完整性/质检 (v3.129 修复批产物) |
| **统一闭环** | **缺** | 执行→反思→注入 没有打通; 洞见无保持度衰减; 无效果归因 |

**诊断**: meshctx 不缺积木, 缺的是把它们串成 GEPA 式闭环的那根线。

## 3. 设计: Self-Evolution Loop v1 (Phase-0, 零 LLM 依赖)

```
任务执行 ──record()──▶ ExperienceStore (JSONL+哈希链, 复用 web3_messaging)
                          │
              reflect() ◀─┘ (周期/手动触发)
      统计蒸馏: task_type × strategy → 成功率; 洞见=自然语言规则
                          │
                          ▼
              InsightStore (复用 FSRS: 洞见=MemoryItem, stability=保持度)
                          │
      ┌─────reinforce()──┘ (新任务结果回灌: 命中洞见且成功→stability↑, 失败→↓)
      ▼
   inject(task_type, k) ──▶ 检索 top-k 洞见 (FSRS 保持度×新鲜度×命中率排序)
      │                        (供 SYSTEM_PROMPT / agent 上下文注入)
      └──▶ 下一次任务执行
```

核心决策 (每条对应 SOTA 依据):
1. **洞见=自然语言规则** (ExpeL 路线): Phase-0 用统计蒸馏 (成功率差>阈值即成规则),
   Phase-1 可选 LLM 改写 (接 chat_tools 既有模型调用)。
2. **洞见保持度用 FSRS** (复用 memory_hierarchy): 高频命中且伴随成功的洞见
   stability 上升 (少复习也记得), 长期无用洞见自然衰减淘汰 — 免费获得
   "遗忘无用经验"能力, 这是 ExpeL 论文没有的 meshctx 特色。
3. **完整性用哈希链** (复用 web3_messaging): 经验/洞见追加即链式签名,
   防止自演化被篡改 (SOTA 安全告诫的直接回应: 自产自销, 零外部注入面)。
4. **效果归因** (GEPA-lite): 每次任务记录 (task_type, strategy, outcome);
   洞见的 score = P(成功|命中洞见) − P(成功|未命中) 的滑动估计。
5. **Phase-0 零 LLM**: 全部统计实现, 离线可用; LLM 反思作为 Phase-1 可选增强。

## 4. Phase-0 接口 (src/core/self_evolution.py)

```python
loop = get_self_evolution()                  # 单例, ~/.meshctx/self_evolution/
loop.record(task_type, strategy, outcome, detail="", duration_ms=0)  # 执行后记录
loop.reflect(min_samples=5)                  # → 新蒸馏洞见数 (统计规则生成)
loop.inject(task_type, k=3)                  # → [str] top-k 洞见 (注入 prompt)
loop.reinforce(task_type, hit_insight_ids, outcome)  # 效果归因回灌
loop.stats()                                 # 闭环健康度 (经验数/洞见数/链校验)
```

## 5. 后续路线 (Phase-1/2, 另行排期)

- **Phase-1**: LLM 反思改写 (粗规则→精炼洞见, 接 chat_tools); SYSTEM_PROMPT 自动
  注入 (web_ui 聊天链路挂 inject); GEPA 式提示变体 Pareto 池 (prompt_registry 对接)。
- **Phase-2**: Voyager 式可执行技能库 (skill_manager 对接, 技能=代码+验证用例);
  跨机共享洞见 (集群 v6 通道 sync, 带哈希链防篡改 — 各实例经验互相增益)。
- **安全边界不变式**: 洞见只从本地执行轨迹生成; 哈希链校验失败即拒绝加载;
  洞见注入只作为上下文参考文本, 永不直接改变权限边界。

## 6. SOTA 来源

- [A Survey of Self-Evolving Agents (arXiv:2507.21046)](https://arxiv.org/abs/2507.21046) ·
  [Awesome-Self-Evolving-Agents](https://github.com/XMUDeepLIT/Awesome-Self-Evolving-Agents)
- [Self-Improvements in Modern Agentic Systems: A Survey (arXiv:2607.13104)](https://arxiv.org/abs/2607.13104)
- [GEPA: Reflective Prompt Evolution (arXiv:2507.19457)](https://arxiv.org/abs/2507.19457) ·
  [gepa-ai/gepa](https://github.com/gepa-ai/gepa)
- [ExpeL: LLM Agents Are Experiential Learners (arXiv:2308.10144)](https://arxiv.org/html/2308.10144v3)
- [RL for Self-Improving Agent with Skill Library (arXiv:2512.17102)](https://arxiv.org/html/2512.17102v2)
- [TT-SI: Self-Improving LLM Agents at Test-Time (arXiv:2510.07841)](https://arxiv.org/abs/2510.07841)
