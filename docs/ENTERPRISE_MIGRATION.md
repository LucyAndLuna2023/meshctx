# Enterprise/Team 代码迁移说明 (2026-08-31)

## 变更
团队/企业版代码已从本开源库 (AGPLv3) 迁移至 **私有库**:
`github.com/LucyAndLuna2023/meshctx-enterprise` (Proprietary)

## 本库保留 (stub 占位)
以下模块保留为 stub (可 import, 调用抛 `EnterpriseFeatureError` → API 501):

| 模块 | 完整实现位置 |
|------|-------------|
| team.py / team_memory.py | meshctx-enterprise |
| swarm.py / agent_swarm.py / agent_swarm_v2.py / swarm_engine.py | meshctx-enterprise |
| agent_teams.py | meshctx-enterprise |
| business_plans.py / billing_payments.py | meshctx-enterprise |
| memory_hierarchy.py / key_vault.py / sso.py / sso_state.py | meshctx-enterprise |

## API 行为
企业版 API (`/api/team/*`, `/api/billing/*`, `/api/swarm/*` 等) 在开源库
返回 **501 enterprise_feature_moved** (完整实现需安装 meshctx-enterprise)。

## 安装私有库恢复完整功能
```bash
pip install git+https://github.com/LucyAndLuna2023/meshctx-enterprise.git
# 或 clone 后设置 PYTHONPATH
```
