# MeshCtx 四层版本边界 (EDITION BOUNDARIES) — 权威口径

> 定稿 2026-09-22 (用户确认: 个人版也有开源和闭源部分)。任何新功能落地前先对表:
> **代码放错库 = 边界事故** (参照 2026-09-22 组通道误放开源库, 已迁正)。

## 四库矩阵

| 库 | 可见性 | License | 定位 | 典型内容 |
|---|---|---|---|---|
| **meshctx** | 🌐 开源 GitHub | AGPLv3 + Commercial | 协议基座/骨架/UI/安全模块/安装器 | cluster/ 单播协议 v6.1 (信封校验/NX去重/journal/路由白名单) · 313 core 骨架模块 · i18n 11语言 · Web UI |
| **meshctx-core** | 🔒 私有 | 双重许可 (Dual Licensing) | **个人版闭源增强** (个人版也装) | mcp_gateway · lsp_tool · desktop_tool · patch_generator · spreadsheet_tool · ppt_generator · obs_integration · dreaming_service · observability · persistence · skill_registry 等 150+ py (独有 12+) |
| **meshctx-team** | 🔒 私有 | Proprietary ($9/人/月) | 团队协作 | team_memory · swarm_review · agent_teams · **cluster_groups (v6.2 部门/项目组通道)** |
| **meshctx-enterprise** | 🔒 私有 | Proprietary ($29/人/月) | 组织治理/合规 | SSO · 审计 · SLA · 私有化 · RBAC 部门树 |

## 安装矩阵 (install-edition.sh)

| Edition | 装载 | 组通道 | SSO/RBAC | core 增强 |
|---|---|---|---|---|
| personal (free) | meshctx | ❌ stub | ❌ stub | 装了 core 就有 |
| team ($9) | + meshctx-team | ✅ | ❌ | ✅ |
| enterprise ($29) | + team + enterprise (enterprise 先合并防占位) | ✅ | ✅ (部门树覆写 ROLE_PROVIDER) | ✅ |

## 门控机制 (四道防线, 防实现放错库)

1. **stub 标记**: 开源侧闭源功能文件头部 `_ENTERPRISE_FEATURE_MOVED` /
   `_IMPLEMENTATION_MOVED` — `_edition.py::_module_is_stub` fail-closed 检测
2. **PEP 562 拒访**: stub 模块任意符号访问抛 `TeamFeatureError` /
   `EnterpriseFeatureError` (守门: tests/test_cluster_groups.py)
3. **API 501**: `/api/team/*` `/api/billing/*` 等企业路由开源库返回
   `501 enterprise_feature_moved`
4. **角色插拔**: `MESHCTX_GROUP_ROLE_PROVIDER` — 团队/企业 RBAC provider
   覆写开源 stub (本机 owner / 他机 member)

## 落地检查单 (新功能必答)

- [ ] 功能属于哪个 edition? (个人基础→开源; 个人增强→core; 团队协作→team; 组织治理→enterprise)
- [ ] 开源侧只留 stub + 标记 + 拒访守门?
- [ ] ENTERPRISE_MIGRATION.md 迁移表已更新?
- [ ] 对应私有库 README 模块表已更新?
- [ ] 说明书 (USER_GUIDE/私有库 docs) 按库口径分别补全?

## 历史

- 2026-08-31: 团队/企业代码自开源库迁出 (ENTERPRISE_MIGRATION.md)
- 2026-09-22: v6.2 组通道误放开源库 → 迁 meshctx-team @6fca0e9;
  开源 stub 化 @3320f64a; 本边界文档建立


## 跨项目职责边界 (2026-09-28 用户划定, 铁律级)

004deepseek/meshctx 线**只负责 meshctx 项目**。以下为**不碰清单** (违规即边界事故):

| 项目线 | 负责方 | meshctx 线禁入事项 |
|---|---|---|
| quant (A股策略/回测/复现) | 002quant (裁定) / 004quant (执行) / 002zcode+004zcode (审计) | 一切策略/回测/复现/数据任务与通道往来 |
| crypto (Binance 交易) | 002bsc (执行) / 002quant (裁定) | 交易引擎/审计/部署 |
| geo 推广 (X/韩语/海外) | 001geo | 推广素材/任务执行 |
| hub 通道运维 | 001admin / 002admin / 003 | 通道部署/清理器/巡检 (meshctx 线只发通报不执行) |

**唯一例外**: 集群通讯基础设施 (cluster/ v6.x) 为 meshctx 项目产物, 其修复与审计属 meshctx 线。
**历史事故**: I-7 (误杀 quant 复现任务, 2026-09-27) — 本表由此立规。
