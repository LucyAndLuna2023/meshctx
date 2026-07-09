# MeshCtx 主页诚实化 + 架构补齐计划 (v3.115.16)
# 002审计: 37项声称, 28项有代码(76%), 9项需修复

## ── Phase A: 修正虚假/过时声称 (1h) ──

### A1. SWE-bench 98.7% → 真实数据
- 当前: 主页 docs/index.md 宣称296/300=98.7%
- 实际: SWE-bench_lite README 目标>30%
- 修复: 主页改为 "SWE-bench: 目标30%+ resolve rate"
  或实现真实SWE-bench runner证明实际分数

### A2. brew install → 移除或实现
- 当前: 主页有brew安装命令, 仓库无Formula
- 修复: 创建 Homebrew Formula 或从主页移除brew行

### A3. 脑区9→13
- 当前: 主页说9脑区, 实际13+
- 修复: docs/index.md更新脑区数量

## ── Phase B: 补5个缺失模块 (3h) ──

### B1. Counterfactual Reasoning (反事实推理)
"如果当时选了方案B会怎样?"
- 输入: 历史决策记录
- 输出: 反事实分析 + 替代方案评分
- 算法: Pearl's do-calculus简化版 + 最近邻匹配

### B2. Behavior Compliance (行为合规)
"agent行为是否符合6条安全规则?"
- 6 Rules: 不泄露密钥/不执行危险命令/不伪造数据/不绕过审批/不无限循环/不欺骗用户
- 实现: 规则引擎 + 输出过滤 + 违规日志

### B3. Predictive Context (预测上下文)
"根据当前上下文预测下一步需要什么"
- 已有cerebellar部分覆盖
- 补充: 上下文预加载 + 前瞻性工具建议

### B4. Forgetting Curve / Ebbinghaus
"不重要信息自然衰减"
- 已有attention_decay + hippocampal decay
- 补充: 独立EbbinghausForgetting模块(间隔重复)

### B5. Info-Geometric Router (信息几何路由)
"Fisher信息度量优化路由决策"
- info_geo_router.py存在但brain_router无Fisher
- 补充: Fisher信息矩阵 + 自然梯度路由

## ── Phase C: 架构文档同步 (0.5h) ──
- README.md 与 docs/index.md 同步
- 版本号统一
- 所有声称→代码可追溯

## 预计: 5h完成, 37/37 100%匹配
