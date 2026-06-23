# meshctx Bug 修复报告 — 2026-06-23

> 备份: tag `backup-before-bugfix-202606230904`, branch `backup/bugfix-20260623`
> 版本: v3.115.2 → v3.115.3

---

## 发现的问题

### 🔴 BUG #1: `/kernel/stats` 500 Internal Server Error

**位置**: `src/main.py:971` + `src/core/kernel.py:PluginManager`

**原因**: `PluginManager` stub 缺少 `list_active()` 方法。调用走 `__getattr__` → `_P` 代理 → `_P.__call__()` → 返回 `_P` 对象。FastAPI JSON 序列化时 `_P` 不可序列化 → 500 错误。无 try/except 保护。

**修复**: 在 `PluginManager` 中添加 `list_active()` 方法，返回 `list(self._plugins.keys())`。

---

### 🟡 BUG #2: `/health` 和 `/api/health` 返回错误数据

**位置**: `src/main.py:3529-3564` + `src/core/health_monitor.py`

**原因**: `health_monitor.py` stub 缺少 `get_health_monitor()` 函数和 `RealtimeHealthMonitor.check_all()` 方法。所有调用走模块级 `__getattr__` → `_P` 代理，`__eq__` 永远返回 `True`。结果永远返回 `{"status":"healthy","modules_ok":0,"modules_total":0}`。

**修复**: 
1. 添加 `get_health_monitor()` 函数
2. 在 `RealtimeHealthMonitor` 添加 `check_all()` 方法

---

### 🟡 BUG #3: PluginManager 缺少 `list_all()` 方法

**位置**: `src/core/kernel.py:PluginManager`

**原因**: `main.py:1011` 调用 `k.plugins.list_all()`，但 `PluginManager` 只有 `__getattr__` → `_P`。依赖 try/except 兜底返回 `[]`。

**修复**: 添加 `list_all()` 方法（别名到 `list()`）。

---

### 🟡 BUG #4: HealthMonitor stub 缺少 `get_health_monitor()` 函数

**位置**: `src/core/health_monitor.py`

**原因**: `main.py` 导入 `get_health_monitor`，但模块只有类定义，走模块级 `__getattr__` → `_P` 代理。

**修复**: 添加模块级 `get_health_monitor()` 函数。

---

## 修复详情

### 1. `src/core/kernel.py` — PluginManager

- 添加 `list_all()` 方法 → 返回 `list(self._plugins.keys())` + 插件详情
- 添加 `list_active()` 方法 → 返回 active 插件列表

### 2. `src/core/health_monitor.py` — HealthMonitor

- 添加 `get_health_monitor()` 模块级函数
- 添加 `RealtimeHealthMonitor.check_all()` 异步方法
- 移除模块级 `__getattr__`（防止绕过 stub 检查）

---

## 测试结果

待执行。

---

## Hermes 集群协同

待调查。
