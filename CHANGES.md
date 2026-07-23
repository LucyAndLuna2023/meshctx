# meshctx Bug 修复 + Hermes 集成报告 — 2026-06-23

> 备份: tag `backup-before-bugfix-202606230904`, branch `backup/bugfix-20260623`
> 版本: v3.115.2 → v3.115.3

---

## 一、Bug 修复 (5个)

### 🔴 BUG #1: `/kernel/stats` 500 Internal Server Error
- **文件**: `src/main.py:971` + `src/core/kernel.py:PluginManager`
- **原因**: `list_active()` 缺失 → `__getattr__` → stub 不可JSON序列化 → 500
- **修复**: 在 `PluginManager` 添加 `list_active()` 方法

### 🟡 BUG #2: `/health` 和 `/api/health` 返回虚假数据
- **文件**: `src/main.py:3529-3564` + `src/core/health_monitor.py`
- **原因**: `get_health_monitor()` + `check_all()` 缺失 → 走 stub 代理 → 永远返回 `modules_ok=0`
- **修复**: 添加 `get_health_monitor()` 函数 + `check_all()` 方法

### 🟡 BUG #3: PluginManager 缺少 `list_all()`
- **文件**: `src/core/kernel.py:PluginManager`
- **修复**: 添加 `list_all()` 方法

### 🟡 BUG #4: HealthMonitor stub 缺少 `get_health_monitor()`
- **文件**: `src/core/health_monitor.py`
- **修复**: 添加模块级函数 + 移除模块级 `__getattr__`

## 二、测试结果

**Smoke test**: 6/6 passed
```
✓ test_plugin_manager_list_all       — list_all() returns []
✓ test_plugin_manager_list_active    — list_active() returns []
✓ test_health_monitor_get_hm         — get_health_monitor() returns RealtimeHealthMonitor
✓ test_health_monitor_check_all      — check_all() returns {ok:3, total:3, error:0}
✓ test_kernel_stats_endpoint_shape   — /kernel/stats returns valid JSON shape
✓ test_hermes_cluster_discovery      — Hermes discovery finds 14 instances
```

**API test**: +2 new endpoints pass (was 29/36, pre-existing stub failures unrelated)

## 三、Hermes 集群协同集成

### 新增文件
- `src/core/hermes_connector.py` (345行) — HermesConnectorPlugin + HermesDiscovery + EventBridge
- `~/.hermes/profiles/meshctx/skills/meshctx-client/SKILL.md` — Hermes 端集成技能

### 新增端点
- `GET /api/hermes/cluster` — 返回 Hermes 集群状态

### 发现结果
```
14 Hermes 实例: wchatgroup, crypto, earnd, quant, meshctx, WSL-New, 
crypto-v1, crypto-v2, spicyspot, bsc, admin, geo, lexai, qa
meshctx profile: 29 skills, status=online
```

### 架构
```
┌────────────┐     ┌────────────┐     ┌────────────┐
│  Hermes    │     │  Hermes    │     │  Hermes    │
│  Agent A   │     │  Agent B   │     │  Agent C   │
└─────┬──────┘     └─────┬──────┘     └─────┬──────┘
      │                   │                   │
      └───────────────────┼───────────────────┘
                          │
                  ┌───────▼────────┐
                  │    meshctx     │  ← HermesConnectorPlugin
                  │ /api/hermes/   │     EventBridge
                  │   cluster      │     HermesDiscovery
                  └────────────────┘
```

## 四、文件修改清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/__init__.py` | 修改 | v3.115.3 |
| `src/core/kernel.py` | 修改 | +list_all(), +list_active() |
| `src/core/health_monitor.py` | 重写 | +get_health_monitor(), +check_all() |
| `src/core/__init__.py` | 修改 | +hermes_connector 注册 |
| `src/core/hermes_connector.py` | 新增 | Hermes集群协同插件 |
| `src/main.py` | 修改 | +/api/hermes/cluster, +HermesConnectorPlugin注册 |
| `tests/test_smoke_v31153.py` | 新增 | 冒烟测试 |

---

## per-conversation 模型切换 (v3.115.25) — 2026-07-24

### 功能
- 每个会话独立选择 AI 模型，切换会话自动恢复对应模型
- Web UI 顶部模型下拉菜单 + 斜杠命令 (`/model`, `/models`, `/help`, `/clear`)
- CLI 斜杠命令 `/model <id>` 切换，`/model` 查看当前

### 新增/修改
| 文件 | 变更 |
|------|------|
| `src/core/conversation_store.py` | load/get_or_create/list_all 恢复 model 字段 |
| `src/main.py` | PATCH /api/conversations/{id}/model + BUILTIN_MODELS 校验 |
| `src/web_ui.py` | 模型下拉菜单 + 斜杠命令 + send()传model |
| `src/cli.py` | /model 无参显示当前模型 |

### 审计
- 004qa 深度审计: P1认证+P2校验+P2格式一致性，已修复闭环 (d276a6b)
