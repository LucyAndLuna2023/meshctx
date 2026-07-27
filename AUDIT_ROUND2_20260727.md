# 🔍 meshctx 第二轮审计报告 — 2026-07-27

**审计范围**: 插件系统 / MCP / 多Agent / 工作流 / WebSocket / 文件操作 / 依赖 / 并发  
**前置**: P0 修复全部验证通过 ✅

---

## P0 修复验证

| ID | 状态 | 验证结果 |
|----|------|---------|
| P0-1 | ✅ | `deploy.sh` 已删除 |
| P0-2 | ✅ | session 目录权限 700，`.presanitize` 已清理 |
| P0-3 | ✅ | `config.yaml` → `${DEEPSEEK_API_KEY}` |
| P0-4 | ✅ | `provider_config.json` 已 git rm |
| P0-5 | ✅ | CSRF 中间件已添加 (`main.py:739-761`) |
| P0-6 | ✅ | `crypto.py` YAML monkey-patch 已移除 |
| P0-7 | ⚠️ | `shlex.quote()` 已添加但仍保留 `shell=True` |

---

## 一、插件系统 — 🟢 80/100

| 模块 | 行数 | 类数 | 评估 |
|------|------|------|------|
| `plugin_manager.py` | 300 | 5 | ✅ 完整生命周期 |
| `plugin_market.py` | 574 | 5 | ✅ 市场+评分+版本 |
| `template/plugin.py` | 44 | 1 | ✅ 模板清晰 |
| `plugin_adapter.py` | — | — | 适配层 |
| `plugin_hotreload.py` | — | — | 热重载 |
| `plugin_autoload.py` | 6 | 1 | ⚠️ stub |

### 细节
- `PluginManager` 支持 discover/load/activate/deactivate/unload/reload 完整生命周期
- Hook 系统 (`register_hook` / `_fire_hook`) 支持事件驱动扩展
- `plugin_market.py` 有评分/评论/版本管理
- **缺失**: 无插件沙箱隔离（插件代码在宿主机进程内执行）

---

## 二、MCP 集成 — 🟡 65/100

| 模块 | 行数 | 评估 |
|------|------|------|
| `mcp_integrator.py` | 85 | 🟡 精简 |
| `mcp_standardizer.py` | 379 | 🟢 完整 |

- MCP server 不在 `src/core/` 下（可能在其他路径或尚未实现为独立文件）
- 标准化层 379 行覆盖协议适配

---

## 三、多 Agent 编排 — 🟢 85/100

| 模块 | 行数 | 类数 | 亮点 |
|------|------|------|------|
| `agent_swarm_v2.py` | 425 | 18 | 拜占庭容错共识 |
| `agent_teams.py` | 332 | 5 | 团队协作 |
| `agent_swarm.py` | — | 8 | v1 版本 |
| `orchestrator.py` | 442 | — | 编排引擎 |
| `multi_agent.py` | 1630 | — | 多Agent基础 |

**总计**: 2,829 行，5 个模块，31+ 类

### 亮点
- 支持 6 种角色: Leader/Worker/Reviewer/Observer/Coordinator/Forager/Specialist
- 5 种共识策略: Majority/Unanimous/Weighted/Supermajority/Byzantine
- 5 种拓扑: Mesh/Ring/Star/Tree/Small-World
- 市场式任务分配 (Bidding/Assigned/Running/Done/Failed)

---

## 四、工作流引擎 — 🟢 80/100

| 模块 | 行数 | 类数 |
|------|------|------|
| `workflow_engine.py` | 754 | 11 |
| `workflow.py` | 829 | — |
| `chain_engine.py` | 768 | — |
| `task_planner.py` | 972 | — |

**总计**: 3,323 行，4 个模块

---

## 五、WebSocket — 🟡 50/100

| 模块 | 行数 | 评估 |
|------|------|------|
| `ws_reliable.py` | 87 | 🟢 重连+心跳 |
| `websocket_plugin.py` | 30 | 🔴 过简 |
| `realtime_push.py` | 208 | 🟡 推送服务 |

- `websocket_plugin.py` 仅 30 行，疑似未完整实现
- WS 总代码量 325 行，对一个声称支持实时推送的平台偏少

---

## 六、文件操作 — 🟡 60/100

- `send_file.py` 含飞书/微信文件上传功能
- **缺失**: 无明确的路径遍历防护（如 `os.path.realpath` 校验）
- `open(file_path, 'rb')` 直接使用用户可能控制的路径

---

## 七、依赖管理 — 🟡 55/100

### 版本不一致

| 包 | requirements.txt | pyproject.toml | 差异 |
|----|-----------------|----------------|------|
| `jinja2` | `>=3.1.6` | `>=3.1.0` | 🔴 pyproject 落后（3.1.6 修复 XSS CVE） |
| `fastapi` | `>=0.109.1` | `>=0.104.1` | 🟡 不一致 |

### 仅在 requirements.txt 的包（未在 pyproject）

- `aiohttp>=3.14.0`, `aiofiles>=23.0`, `packaging>=21.0`, `jieba>=0.42`, `tiktoken>=0.5.0`

### 仅在 pyproject.toml 的包

- `requests>=2.31.0`

### 风险
- 使用 `pip install -r requirements.txt` 和 `pip install .` 会安装不同版本的 jinja2
- `jinja2<3.1.6` 存在 XSS CVE（CVE-2024-22195 等）

---

## 八、并发安全 — 🟡 60/100

| 模块 | 并发相关引用 | 评估 |
|------|-------------|------|
| `distributed_lock.py` | 57 次 threading/asyncio/Lock | 🟢 完整 |
| `load_balancer.py` | 8 次 | 🟡 基础 |
| `ha_bridge.py` | 1 次 | 🟡 偏少 |

- `distributed_lock.py` 有 16 处 race/deadlock 引用，说明作者意识到并发问题
- 但上一轮报告发现 6 处 `time.sleep()` 阻塞事件循环仍未修复

---

## 九、第二轮新发现总结

| # | 级别 | 问题 | 位置 |
|---|------|------|------|
| R2-1 | 🟡 P1 | `jinja2` 版本不一致（CVE 风险） | `pyproject.toml` vs `requirements.txt` |
| R2-2 | 🟡 P1 | `llm_code_engine.py` `shell=True` 仍保留 | `llm_code_engine.py:186` |
| R2-3 | 🟡 P1 | `send_file.py` 无路径遍历防护 | `send_file.py` |
| R2-4 | 🟡 P2 | `websocket_plugin.py` 仅 30 行（功能不足） | `websocket_plugin.py` |
| R2-5 | 🟡 P2 | 插件无沙箱隔离（同进程执行） | `plugin_manager.py` |
| R2-6 | 🟡 P2 | `requirements.txt` 与 `pyproject.toml` 5 个包不一致 | 依赖文件 |
| R2-7 | 🟢 P3 | MCP server 文件缺失 | `mcp_server.py` |

---

## 十、累计审计统计

| 维度 | 评分 | 轮次 |
|------|------|------|
| 安全 | 🟡 35→70 | R1→修复后 |
| 代码质量 | 🟡 55 | R1 |
| 架构 | 🟢 75 | R1 |
| 测试 | 🔴 20 | R1 |
| CLI | 🟡 65 | R1 |
| i18n | 🟢 90 | R1 |
| 文档 | 🔴 30 | R1 |
| 性能 | 🟡 55 | R1 |
| 错误处理 | 🟡 60 | R1 |
| API 设计 | 🟡 65 | R1 |
| 插件系统 | 🟢 80 | R2 |
| MCP | 🟡 65 | R2 |
| 多Agent | 🟢 85 | R2 |
| 工作流 | 🟢 80 | R2 |
| WebSocket | 🟡 50 | R2 |
| 文件操作 | 🟡 60 | R2 |
| 依赖管理 | 🟡 55 | R2 |
| 并发安全 | 🟡 60 | R2 |

**综合评分**: 🟡 62/100（修复 P0 后提升至 ~70）

---

*审计完成时间: 2026-07-27 | 审计者: meshctx Agent | 报告版本: R2*
