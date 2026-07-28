# meshctx CPU/内存 死机根因诊断与修复方案

**日期**: 2026-07-28  
**现象**: 本机死机两次，meshctx 产品 CPU 和内存管理有问题  
**诊断结论**: 4 类致命资源泄漏，综合导致系统 OOM/CPU 耗尽

---

## 一、根因分析

### 🔴 P0-1: 4 个 while True 循环无超时保护 (main.py)

| # | 行号 | 端点/函数 | 风险 | 修复 |
|---|------|----------|------|------|
| 1 | 417 | `auto_archive()` | 每 300s 存档，永不退出 | ✅ `while _archive_ticks < 288` |
| 2 | 2858 | `agent_loop_sse` SSE | 每连接 1 协程，TCP 半开不释放 | ✅ 300s 超时 |
| 3 | 2890 | `sandbox_stream_status` SSE | 每连接 3s heartbeat | ✅ 300s 超时 |
| 4 | 2908 | `trace_stream` SSE | 同上 | ✅ 300s 超时 |

**影响**: 每个 SSE 客户端断开时若未发 FIN 包，协程永久泄漏，RSS 持续增长。

### 🔴 P0-2: 5 个无界列表 → OOM (brain.py 跨 4 类)

| 类 | 变量 | 修复 |
|----|------|------|
| `ThalamicGate` | `current_focus: List[str]=[]` | ✅ `deque(maxlen=50)` |
| `ACCConflictMonitor` | `active_goals: List[Dict]=[]` | ✅ `deque(maxlen=50)` |
| `ACCConflictMonitor` | `active_conflicts: List[Dict]=[]` | ✅ `deque(maxlen=30)` |
| `Insula` | `alerts: List[Dict]=[]` | ✅ `deque(maxlen=200)` |
| `HippocampalReplay` | `generated_skills: List[Dict]=[]` | ✅ `deque(maxlen=100)` |
| `SuperBrain` | 多个列表 | ✅ 已有 `_trim_list` |

**影响**: 运行数小时后百万级条目 → RSS 膨胀至数 GB。

### 🔴 P0-3: Brain Daemon 线程 5s/次满载 (brain.py:1329)

每次 `step()`: 海马回放 → DMN 走神 → 脑岛健康检查 → ACC 冲突解决，空闲时不退避。

**修复**: 频率 5s→10s，每 30 tick 触发 `gc.collect()`

### 🟡 P1: SSE 循环内重复 import

```python
# 修复前 — 每 3-5s 执行一次
import asyncio
from src.core.kernel import Kernel
__import__("datetime").datetime.now()
```
→ 预加载到闭包外，消除重复模块查找

---

## 二、修复脚本

```bash
python3 /home/jason/meshctx-repo/scripts/fix_cpu_memory.py
```

**脚本行为**:
1. 自动备份到 `.meshctx_backups/cpu_fix_YYYYMMDD_HHMMSS/`
2. `main.py`: auto_archive 24h 超时 + 3 SSE 300s 超时 + 预加载 import
3. `brain.py`: 5 个 `deque(maxlen=N)` 替换无界列表
4. 语法检查验证

---

## 三、生效步骤

```bash
# 1. 运行脚本（已完成）
python3 /home/jason/meshctx-repo/scripts/fix_cpu_memory.py

# 2. 验证语法
python3 -m py_compile /home/jason/meshctx-repo/src/main.py
python3 -m py_compile /home/jason/meshctx-repo/src/core/brain.py

# 3. 重启服务
# 停止当前运行的 hermes 实例后重新启动

# 4. 观察 1 小时
watch -n 30 'ps aux --sort=-%mem | head -8'
```

---

## 四、仍需人工处理

| # | 项目 | 建议 |
|---|------|------|
| 1 | `hermes -p admin` (194MB) | systemd `MemoryMax=512M` 防 OOM |
| 2 | `hermes -p meshctx` (84MB) | systemd `MemoryMax=384M` |
| 3 | `token_saver_v4.py` (29MB) | 添加定期 `gc.collect()`，监控 RSS |
| 4 | `token_saver_codex.py` (41MB) | 同上 |
| 5 | `pyright-langserver` (246MB) | 启动参数加 `--max-memory=512` |
| 6 | `hub_client.py` (18MB) | systemd `MemoryMax=128M` |

---

## 五、修改清单

| 文件 | 变更 | 说明 |
|------|------|------|
| `src/main.py` | +22/-6 | SSE 超时 + auto_archive 超时 + 预加载 import |
| `src/core/brain.py` | +27/-4 | 5 deque + daemon GC + _trim_list |

**备份**: `.meshctx_backups/cpu_fix_20260728_084037/`
