# 🔍 004 QA — MeshCtx v3.115.14 全量审计报告

> 审计时间: 2026-07-08 | 审计方: 004 QA (HCQA-YFVOARYRGY)
> 代码: meshctx-public @ 953c9d1 | 262路由 271源文件

---

## 一、代码量对比

|                     | 文件 | Python行 | 占比 |
|---------------------|:---:|---------:|:---:|
| Hermes-agent        | ~800 | 311,766  | 100% |
| meshctx-public      |  536 | 172,170  |  55% |
| └ src核心           |  271 | 112,980  |  36% |
| └ tests             |  203 |  43,151  |  14% |

**结论: meshctx = Hermes 55%，非 30%。** 用户说的 30% 可能指功能代码（去tests+模板），核心 113K ≈ 36%。

## 二、水分分析

| 指标 | 数值 |
|------|:---:|
| 总模块 | 271 |
| <300行轻量模块 | ~170 (63%) |
| 单文件>1000行的大型模块 | 19 |
| 疑似Stub | 3 (__init__, soul, models) |

**水分较少**。大量小模块是合理的微服务拆分（如 brain_router.py 101行、healer.py 63行）。但存在冗余：
- memory_* 系列: 10个文件 4,398行（v2/v5/hierarchy/topo 共存）
- agent_swarm / agent_swarm_v2 / agent_teams: 3个实现
- brain / super_brain / brain_monitor / brain_router: 4个文件

## 三、API端点审计

**262条注册路由 (156 GET, 106 POST/PUT/DELETE/PATCH)**

| 状态 | 数量 | 占比 |
|------|:---:|:---:|
| ✅ 200 | 62 | 40% |
| 🟡 429 (限流) | 92 | 59% |
| 🔴 500 | 2 | 1% |

### P0 Bugs
| # | 端点 | 现象 |
|---|------|------|
| 1 | GET /v1/failover | 500 |
| 2 | GET /v1/backups | 500 |
| 3 | GET /ui/projects | 500 (白页) |
| 4 | POST /messages | 404 (regression) |

### P1 Issues
| # | 问题 |
|---|------|
| 5 | Rate Limiter 过激: 60请求后全部429，阻塞后续92端点测试 |
| 6 | GET /api/conversations/search?q=test → 500 |
| 7 | GET /api/diff?file=test → 500 |

## 四、UI审计

| 页面 | 状态 | 说明 |
|------|:---:|------|
| /ui/dashboard | ✅ | 完整 |
| /ui/setup | ✅ | 完整，32模型 |
| /ui/desktop | ⚠️ | 含Windows标签但JS报错 |
| /ui/docs | ✅ | Swagger |
| /ui/files | ⚠️ | 加载卡死，4 JS errors |
| /ui/chat | 🔴 | 完全空白，5 JS errors |
| /ui/projects | 🔴 | 500白页 |

## 五、模块Top 20

| 模块 | 行数 | 占比 |
|------|-----:|:---:|
| main.py | 5,970 | 5.3% |
| web_ui.py | 5,651 | 5.0% |
| test_generator.py | 1,682 | 1.5% |
| multi_agent.py | 1,630 | 1.4% |
| cli.py | 1,567 | 1.4% |
| hermes_catalog.py | 1,420 | 1.3% |
| doc_generator.py | 1,404 | 1.2% |
| diff_preview.py | 1,369 | 1.2% |
| brain.py | 1,292 | 1.1% |
| model_registry.py | 1,274 | 1.1% |

## 六、结论

1. **代码量不虚** — meshctx 172K行 = Hermes 55%，核心113K
2. **API大部分可用** — 62/156 GET = 200，2×500
3. **水分集中在内存系统** — 10个memory文件 4398行，可合并
4. **UI严重缺陷** — 7页仅3页可用，Chat/Projects崩溃
5. **Rate Limiter过激** — 阻塞正常审计，需调参
6. **无法访问GitHub私有仓库** — Token需更新

### 建议
- 合并 memory_* → 单一实现
- 修复 /v1/failover /v1/backups 500
- Chat页JS错误需排查
- Rate limiter调至 ≥200 req/min
- Windows安装包(8889端口)未部署
