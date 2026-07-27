# 🔒 meshctx 安全审计修复报告 — 2026-07-27

**审计源**: `AUDIT_SECURITY_20260727.md`  
**修复执行**: meshctx Agent  
**范围**: `meshctx-repo/` + `.meshctx/` 部署实例

---

## 📂 代码路径

| 内容 | 路径 | 状态 |
|------|------|------|
| meshctx 产品代码 | `/home/jason/meshctx-repo/` | main `470e9ab` |
| meshctx.com 网站 | `/home/jason/meshctx-repo/` → `docs/` (gh-pages) | `b25cf16` |
| 网站独立拷贝 | `/home/jason/meshctx-website/` | 已导出 |
| 部署运行实例 | `/home/jason/.meshctx/` | 已同步 |

---

## ✅ 已修复 — P0 严重漏洞 (4/4)

### P0-1 🔴 Session 文件泄露真实 API Key → ✅ 已修复
- 删除 10 个 `*.presanitize` 泄露文件
- `sessions/` 目录权限 `664` → `700`
- ⚠️ 需用户手动在 DeepSeek 控制台轮换 Key: `sk-9af...c06f`, `sk-adc...dcf4`

### P0-2 🔴 config.yaml 含真实 API Key → ✅ 已修复
- `key: enc:sk-b6c...613f` → `key: ${DEEPSEEK_API_KEY}`
- 同时在 `meshctx-repo/` 和 `.meshctx/` 修复

### P0-3 🔴 provider_config.json 未受 gitignore 保护 → ✅ 已修复
- 提交 `aad1f41` 已从 git 历史清除
- 文件 `{"key":"***"}` 已脱敏，本地保留

### P0-4 🔴 无 CSRF 保护 → ✅ 已修复
- 新增 `csrf_middleware` 中间件
- 验证 Origin/Referer/X-Requested-With 头
- 覆盖所有 POST/PUT/DELETE/PATCH 端点
- 非浏览器客户端（curl 等）无 Origin 头时自动放行

---

## ✅ 已修复 — P1 高危问题 (5/5)

### P1-1 🟡 CORS allow_headers 过于宽松 → ✅ 已修复
- `allow_headers=["*"]` → `["Authorization", "Content-Type", "X-Requested-With"]`

### P1-2 🟡 Session Cookie 缺少 secure flag → ✅ 已修复（此前已修）
- `main.py:700` 已有 `secure=is_https`，动态判断 HTTPS

### P1-3 🟡 速率限制清理逻辑缺陷 → ✅ 已修复
- `_rate_limits.clear()` 全量清空 → 滑动窗口过期清理
- 仅清理 RATE_WINDOW(60s) 外的旧条目，保留活跃数据
- `_suspicious_ips` 同样改为滑动窗口

### P1-4 🟡 API Key 撤销按哈希前缀匹配 → ⬜ 不存在
- 审计引用的 `src/core/auth_v2.py:252` 文件尚未创建
- 当前 Key 管理在 `web_ui.py` 中，无此前缀匹配问题

### P1-5 🟡 _StubClass 静默失败 → ✅ 已修复（此前已修）
- `MESHCTX_STRICT=1` 环境变量已实现严格模式
- `_warn_once()` 已实现 RuntimeWarning
- `has_module()` / `available_modules()` API 已存在

---

## ⬜ P2 — 低优先级 (6 项，未修)

| 编号 | 问题 | 说明 |
|------|------|------|
| P2-1 | 密码强度视觉与实际不一致 | 前端 `auth.js`，已知问题 |
| P2-2 | Auth Token 存 localStorage | 代码已自注 TODO |
| P2-3 | Dockerfile root 用户 | 添加 `USER 1000:1000` |
| P2-4 | 遗留 `index.html.local_backup` | 删除即可 |
| P2-5 | 版本号不一致 | `.data_version` vs `version_info.txt` |
| P2-6 | meshctx.yaml 模板暴露字段 | 公开配置暗示内部架构 |

---

## 📊 修复统计

| 优先级 | 总数 | 已修复 | 不存在 | 未修 |
|--------|------|--------|--------|------|
| P0 严重 | 4 | **4** | 0 | 0 |
| P1 高危 | 5 | **4** | 1 | 0 |
| P2 低 | 6 | 0 | 0 | **6** |
| **合计** | **15** | **8** | **1** | **6** |

---

*报告由 meshctx Agent 于 2026-07-27 生成*
