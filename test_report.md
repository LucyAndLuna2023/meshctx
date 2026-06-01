# MeshCtx 测试报告 — 2026-06-01 17:32

## 1. 服务器状态 (47.120.0.239)

### 1.1 服务状态
| 项目 | 状态 | 说明 |
|------|------|------|
| meshctx.service | ACTIVE (running) | PID 728536, 启动6分钟, 内存82MB, CPU 18s |
| nginx | ACTIVE | 反向代理 :443 -> :3001 |
| systemd enabled | **DISABLED** | **BUG: 重启后服务不会自动启动** |
| uptime | 23天 | 系统稳定 |

### 1.2 API 验证
| 端点 | 本地结果 | 远程结果 | 说明 |
|------|----------|----------|------|
| http://:3001/api/health | 200 OK, {"status":"ok"} | 301 -> HTTPS | 本地正常 |
| http://:3001/api/version | 200, v3.83.0/123模型/37 providers | 301 -> HTTPS | 版本正确 |
| http://:3001/ (root) | **200 空响应** | 301 -> HTTPS | **BUG: 根路径返回空页面** |
| https://:443/api/health | **本地可访问** | **HTTP 000 (超时)** | **BUG: 外部HTTPS不可达** |
| https://meshctx.com/ | **HTTP 000 (SSL证书错误)** | - | **BUG: CDN/DNS可能未正确配置** |

### 1.3 服务文件
```ini
[Unit]
Description=meshctx v1.0
After=network.target

[Service]
Type=simple
User=root
Environment=DEEPSEEK_API_KEY=***
Environment=MESHCTX_MODEL=deepseek:v4-pro
WorkingDirectory=/opt/meshctx
ExecStart=/opt/meshctx/venv/bin/python -m uvicorn src.main:app --host 0.0.0.0 --port 3001
Restart=always
RestartSec=5
```

### 1.4 系统资源
| 资源 | 使用 | 说明 |
|------|------|------|
| 磁盘 | 16G/40G (42%) | 正常 |
| 内存 | 424M/3.4G | 正常 |
| Swap | **0B (无)** | **BUG: 无swap，OOM风险** |
| OOM事件 | 无 | 当前无OOM记录 |

---

## 2. Bug 清单

### 2.1 CRITICAL (严重)

| # | 文件/位置 | 问题 | 风险 |
|---|-----------|------|------|
| C1 | systemd meshctx.service | **服务未enabled，重启后不自动启动** | 服务中断 |
| C2 | HTTPS 外部访问 | **外部无法通过HTTPS访问API (HTTP 000)** | 用户无法访问 |
| C3 | meshctx.com | **SSL证书错误或DNS未配置** | 官网不可达 |
| C4 | src/main.py:root endpoint | **根路径返回200空响应 (content-length: 0)** | 前端无法加载 |
| C5 | manager_key.json | **64字符secret_key和public_key直接存放在仓库中** | 密钥泄露 |
| C6 | src/core/hooks_engine.py:229 | **eval() 执行动态代码** | 远程代码执行风险 |
| C7 | src/main.py | **CORS allow_origins 包含 * (通配符)** | 跨站请求伪造风险 |
| C8 | 服务器 | **无swap分区 (3.4G RAM, 0 swap)** | 内存耗尽时OOM杀进程 |

### 2.2 HIGH (高)

| # | 文件/位置 | 问题 | 说明 |
|---|-----------|------|------|
| H1 | src/main.py | **6711行超大单文件** | 难以维护、难以测试 |
| H2 | src/web_ui.py | **6173行超大单文件** | 难以维护、难以测试 |
| H3 | 全代码库 | **117处 bare except (裸except)** | 吞掉SystemExit/KeyboardInterrupt, 使调试极其困难 |
| H4 | 全代码库 | **98处 except...pass** | 静默吞异常，错误无声消失 |
| H5 | src/core/hot_reload.py vs src/core/hotreload.py | **重复文件，43%内容重叠** | 命名不一致，维护两份 |
| H6 | requirements.txt | **0/13 包有版本约束** | 不可复现构建，依赖漂移 |
| H7 | .env 文件 | **不存在** | 运行时配置可能失败 |
| H8 | mcp_config.json | **空文件 (2字节)** | MCP功能可能不可用 |
| H9 | __pycache__/meshctx_desktop.cpython-312.pyc | **编译字节码已提交到git** | 增加仓库体积，可能过期 |
| H10 | src/main.py | **无rate limiting** | API被滥用风险 |
| H11 | systemd service | **Environment中明文API Key** | 密钥安全管理问题 |

### 2.3 MEDIUM (中)

| # | 文件 | 行数 | 问题 |
|---|------|------|------|
| M1 | src/core/platform_fs.py | 1 | SyntaxWarning: invalid escape sequence |
| M2 | src/cli.py | 102处 | 生产代码中使用print()而非logger |
| M3 | src/browser_tool.py | 93 | bare except |
| M4 | src/chat_tools.py | 102-103 | bare except + swallowed |
| M5 | src/cli.py | 502-538 | bare except + swallowed |
| M6 | src/gateway.py | 98-99,350 | bare except + swallowed + 硬编码密钥 |
| M7 | src/model_adapter.py | 47,117,150 | bare except + 硬编码密钥 |
| M8 | src/core/alert_engine.py | 50,57 | bare except |
| M9 | src/core/auto_healer.py | 45-76 | 6处bare except |
| M10 | src/core/desktop_agent.py | 34-67 | 6处bare except |
| M11 | src/core/env_diag.py | 20-41 | 4处bare except |
| M12 | src/core/websocket_plugin.py | 76,118,131,300 | bare except + swallowed |
| M13 | src/core/win_admin.py | 285-520 | 8处bare except + 3处swallowed |
| M14 | src/main.py | 多处 | 60+ bare except |
| M15 | src/core/gateway_connectors.py | 139,141 | 可能的硬编码密钥 |
| M16 | src/core/telegram_router.py | 51 | 可能的硬编码密钥 |
| M17 | src/core/pipeline_bench.py | 67 | 可能的硬编码密钥 |
| M18 | src/llm_extractor.py | 22,66,74,81,89 | 硬编码密钥 + 3处bare except + swallowed |
| M19 | src/core/self_healing2.py | - | 命名不规范，暗示有v1存在但找不到 |

### 2.4 LOW (低)

| # | 文件 | 说明 |
|---|------|------|
| L1 | pyproject.toml | 有版本号 OK |
| L2 | .gitignore | 包含.env OK |
| L3 | tests/ | 166测试文件, 4200断言 |

---

## 3. bare except 分布统计

| 文件 | bare except 数量 |
|------|-----------------|
| src/main.py | 60+ |
| src/core/healer.py | 2 |
| src/core/win_admin.py | 5 |
| src/core/auto_healer.py | 6 |
| src/core/desktop_agent.py | 6 |
| src/core/websocket_plugin.py | 3 |
| src/core/env_diag.py | 4 |
| src/core/knowledge_sync.py | 4 |
| src/core/performance.py | 3 |
| src/core/subconscious.py | 3 |
| src/llm_extractor.py | 3 |
| src/browser_tool.py | 1 |
| src/chat_tools.py | 1 |
| src/cli.py | 1 |
| src/gateway.py | 1 |
| src/model_adapter.py | 2 |
| src/cron.py | 1 |
| 其他 core/* | 30+ |
| **总计** | **117处** |

---

## 4. 修复建议 (优先级排序)

### P0 — 立即修复
1. `systemctl enable meshctx.service` — 确保重启后自动启动
2. 排查HTTPS外部不可达: 检查阿里云安全组是否放行443端口
3. 修复根路径: main.py添加 `@app.get("/")` 返回index.html
4. 移除manager_key.json中的真实密钥, 改用环境变量
5. 配置swap: `fallocate -l 2G /swapfile && mkswap /swapfile && swapon /swapfile`

### P1 — 本周修复
6. 替换所有bare except为具体异常类型 (117处)
7. 替换所有except...pass为logging.error (98处)
8. 移除hooks_engine.py中的eval()
9. 限制CORS allow_origins为具体域名
10. 为requirements.txt添加版本约束

### P2 — 架构优化
11. 拆分main.py (6711行) 为模块化routers
12. 拆分web_ui.py (6173行) 为组件
13. 删除hot_reload.py/hotreload.py重复文件
14. 从.git中移除__pycache__.pyc
15. 添加rate limiting中间件

---

## 5. 测试覆盖率

- 测试文件: 166
- 源代码文件: 212
- 测试断言: 4200
- 覆盖率比例: ~78% (按文件数)

---

## 6. 版本信息

- 服务器版本: v3.83.0
- 模型数: 123
- 提供商: 37
- 插件: 9
- 内置测试: 1623
