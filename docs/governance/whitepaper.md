# MeshCtx Agent Governance 白皮书 — 安全可控的自主 Agent 基座

- 编号: MCTX-GOV-2026-0903　版本: v1.0　日期: 2026-09-03
- WP8 (MCTX-PLAN-2026-0903 P2-1) — 把先发优势变成话语权 (002meshctx/002codex 审计共识)

## 1. 背景: Agent 治理进入监管时代

2026-08/09 信号: 英国 AISI 披露 OpenAI/Anthropic 模型测试出现"伪造身份越权访问",
欧盟与两厂商紧急对话; NIST 推动"主动能身份 (Non-human Identity)/最小权限/可审计";
Cisco 将 Zero Trust 扩展到 AI Agent。结论: **能办事的 Agent 必须有可治理的底座**,
否则企业/监管不会放行。MeshCtx 从第一天就把审批/配额/审计/身份做成运行时基座 —
本白皮书把该基座以标准语言 (NIST/Cisco) 表达。

## 2. 映射总表 (NIST 主动能框架 × MeshCtx 实现)

| NIST / Zero Trust 原则 | MeshCtx 实现 | 模块 |
|---|---|---|
| 主动能身份 (Non-Human Identity) | agent 注册 (AgentIdentity) + API key 鉴权 (auth_v2) + 任务卡 owner 归因 | agent_governance.py / auth_v2.py / task_cards.py |
| 最小权限 | 危险动作审批流 (action_gate → needs_approval → WAITING_APPROVAL → decide) + 额度配额 (HubQuota) + 沙箱 cap-drop ALL (WP7) | approval.py / task_cards.py / sandbox_policy.py |
| 可审计 | 进程内审计 (AgentGovernance._audit AuditEntry) + 卡 timeline 全事件 + 全链路遥测 trace (WP1 span/工具/审批/取消事件) | agent_governance.py / task_cards.py / telemetry.py |
| 不信任任何会话 (Zero Trust 语境) | 每次请求鉴权; 跨 owner 403/404; 写操作拒匿名; 后台卡重启恢复仍过配额与审批 | task_cards_api.py / routines.py |
| 分段/隔离 | 沙箱禁网 + 只读 rootfs + 唯一 workspace (WP7); 多机 hub 以 profile 隔离 | sandbox_policy.py / hub |

## 3. 案例对照 (以 2026 公开事件做压力测试)

1. **AISI 伪造身份越权**: Agent 冒用他人身份访问资源。
   MeshCtx 对位: owner 归因 (卡/例行/Routine 全部归属创建者) + 跨 owner 404
   (不泄露存在性) + key 鉴权白名单; 远程写操作必须认证。
2. **Artifactory 零日沙箱逃逸**: 容器内提权逃逸到宿主。
   MeshCtx 对位 (WP7): cap-drop ALL / no-new-privileges / 非 root / 只读 rootfs /
   network none / env 白名单 — 逃逸路径静态分级 high 直接拒。
3. **审批疲劳/超时自动放行**: 用户不看审批导致风险动作默认通过。
   MeshCtx 对位: 审批超时**自动拒绝** (120s, 非放行); 卡取消即时 reject 挂起审批
   (002codex P3 已修)。

## 4. 治理 API (只读聚合, WP8)

`/api/governance/*` (计划): 复用 agent_governance 进程内数据 + task_cards 审批/
配额/审计, 只读聚合:
- `GET /api/governance/agents` — 已注册 agent 身份 (主动能身份清单)
- `GET /api/governance/audit?window=` — 审计条目 (审批/执行/遥测事件)
- `GET /api/governance/quota` — 额度用量
企业版在此基础上提供 SOC2 类导出 (审计日志归档格式契约)。

## 5. 商业与话语权

- 个人版 (开源): 治理基座全量内置 — 审批/配额/审计/遥测本地可用 (open-core 定位)。
- 团队/企业版: 治理面板 (trace 检索/审计导出/额度看板) + 托管导出。
- 白皮书与 meshctx.com 治理页 (10 语言) 面向企业采购方输出"NIST 对标"故事。

## 6. 参考

- NIST AI RMF / 主动能身份指引; Cisco Zero Trust for AI Agent 框架;
- MCTX-RES-2026-0903 第七章差距矩阵 (#10 安全治理 = 🏆 相对领先项);
- MCTX-PLAN-2026-0903 WP8 验收: 章节完整性 checklist + 治理 API 测试 + i18n 页。
