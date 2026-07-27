# 🔍 meshctx 安全审计报告 — 2026-07-27

**审计范围**: `meshctx-repo/` (产品代码) + `meshctx-website/` (网站) + `.meshctx/` (运行实例)  
**审计角度**: 密钥泄露、认证安全、网络/API 安全、沙箱安全、前端 XSS/CSP、代码质量

---

## 一、总体健康度: 🟡 70/100

| 维度 | 评分 | 关键发现 |
|------|------|---------|
| 密钥管理 | 🔴 25 | 3 处明文 API Key 泄露 |
| 认证/授权 | 🟡 65 | 无 CSRF、session 无 secure flag |
| 网络安全 | 🟡 60 | CORS 过于宽松、速率限制可被绕过 |
| 沙箱安全 | 🟢 80 | Docker + subprocess 双重隔离，设计良好 |
| 前端安全 | 🟡 65 | 密码强度显示不一致、token 存 localStorage |
| 代码安全 | 🟡 65 | 无代码注入点、但 `_StubClass` 静默失败未修复 |
| 部署安全 | 🟡 60 | Docker root 用户、session 文件 664 权限 |

---

## 二、🔴 P0 — 严重安全漏洞（需立即修复）

### P0-1 🔴 Session 文件泄露真实 API Key

- **位置**: `/home/jason/.meshctx/sessions/*.presanitize`
- **泄露内容**: DeepSeek API Key `sk-9af61995b6274f218f29a1ec31eac06f` 和 `sk-adc7bcd066cd4f4781280c6955a1dcf4` 在 **6+ 个 session 文件**中以明文存在
- **文件权限**: `-rw-rw-r--` (664)，任何同组用户可读
- **影响**: API Key 已被写入本地磁盘明文文件，且权限过于宽松。如果机器被入侵或 session 文件被上传到 GitHub，攻击者可直接使用该 Key
- **修复**:
  1. 立即在 DeepSeek 控制台撤销并轮换这两个 Key
  2. 删除 `~/.meshctx/sessions/` 下所有 `*.presanitize` 文件
  3. 实现 session 序列化时的密钥脱敏逻辑（如用 `***REDACTED***` 替换）
  4. session 目录权限改为 `700`

### P0-2 🔴 `config.yaml` 含真实 API Key

- **位置**: `/home/jason/meshctx-repo/config.yaml:6`
- **内容**: `key: enc:sk-b6c...613f`
- **影响**: 虽然标注了 `enc:` 前缀暗示"加密"，但实际只是个字符串前缀，Key 仍在版本库中明文可见
- **修复**: 移除该行，使用 `${DEEPSEEK_API_KEY}` 环境变量替代

### P0-3 🔴 `provider_config.json` 未受 gitignore 保护

- **位置**: `/home/jason/meshctx-repo/provider_config.json`
- **内容**: `{"openai": {"key": "sk-openai-browser", ...}}`
- **影响**: `.gitignore` 第 36 行写了 `provider_config.json`，但该文件**仍然存在于仓库中**（此前被 `git add -f` 或 ignore 规则添加前已提交）
- **修复**: `git rm --cached provider_config.json` 并确认远程仓库已清除

### P0-4 🔴 无 CSRF 保护

- **位置**: `src/core/auth_v2.py` 的 `/api/auth/login`、`/api/auth/logout`、`/api/auth/keys` 端点
- **问题**: 所有认证操作无 CSRF token 校验。攻击者可构造恶意网页诱导已登录管理员执行 API Key 创建/撤销操作
- **修复**: 添加 CSRF token 中间件，或在关键端点要求自定义 header（如 `X-Requested-With`）

---

## 三、🟡 P1 — 高优先级安全问题

### P1-1 🟡 CORS 过于宽松

- **位置**: `src/main.py:511-515`
- **问题**: `allow_methods=["*"]`, `allow_headers=["*"]`, `allow_credentials=True`
- **CORS 规范**: `allow_credentials=True` 时，`allow_origins` 不能为 `*`（meshctx 用了具体列表✅），但 `allow_headers=["*"]` 仍过于宽松
- **修复**: 将 `allow_headers` 限制为 `["Authorization", "Content-Type"]`

### P1-2 🟡 Session Cookie 缺少 `secure` flag

- **位置**: `src/core/auth_v2.py:196`
- **当前**: `set_cookie("meshctx_session", ..., httponly=True, max_age=86400, samesite="lax")`
- **缺失**: 没有 `secure=True`
- **影响**: 在 HTTPS 部署时 cookie 仍可通过 HTTP 传输
- **修复**: 添加 `secure=True`（或根据 `request.url.scheme` 动态设置）

### P1-3 🟡 速率限制的清理逻辑存在缺陷

- **位置**: `src/main.py:560-565`
- **问题**: 每 300 秒 `_rate_limits.clear()` 和 `_suspicious_ips.clear()` 全部清空
- **影响**: 攻击者只需等 5 分钟即可重新发起暴力破解，可疑 IP 追踪也被清空
- **修复**: 用滑动窗口替代全量清空，保留至少 30 分钟历史

### P1-4 🟡 API Key 撤销按哈希前缀匹配

- **位置**: `src/core/auth_v2.py:252`
- **问题**: `matched = [kh for kh in keys if kh.startswith(key_prefix)]` — 仅用 SHA256 前 12 位 hex 匹配
- **影响**: 12 位 hex = 48 bits，在大量 Key 时有碰撞风险
- **修复**: 要求传入完整 key 或使用更长的前缀（16+ 位），或直接用 key ID 而非 hash 前缀

### P1-5 🟡 `_StubClass` 静默失败 — 002 审计修复未落地

- **位置**: `src/core/__init__.py`
- **AUDIT_002** 已裁定为「条件批准，需三阶段修复」，但目前代码**仍使用原始 `_StubClass`**（静默返回 stub），未进入阶段 1（MESHCTX_STRICT 警告模式）
- **影响**: 模块缺失时静默失败，隐藏 bug
- **修复**: 按 002 审计的阶段 1 方案实施

---

## 四、🟢 P2 — 中低优先级问题

### P2-1 🟢 密码强度视觉与实际验证不一致

- **位置**: `meshctx-website/docs/auth.js`
- **已知问题** (R8#53, R8#54): `checkPasswordStrength` 视觉条显示绿色但 `isPasswordStrong` 拒绝；`changePassword` 不调用 `isPasswordStrong`
- **状态**: R8 审计标记为已修复但需验证

### P2-2 🟢 Auth Token 存 localStorage

- **位置**: `meshctx-website/docs/auth.js:132`
- `var _token = localStorage.getItem('meshctx-token') || null;  // ⚠️ P1: localStorage XSS risk — TODO: migrate to httpOnly cookie`
- 代码注释已自认 XSS 风险，但仍在使用 localStorage

### P2-3 🟢 Dockerfile 以 root 运行

- **位置**: `Dockerfile:20`
- 无 `USER` 指令，容器以 root 身份运行
- **修复**: 添加 `USER 1000:1000` 或创建专用用户

### P2-4 🟢 `index.html.local_backup` 遗留文件

- **位置**: `/home/jason/meshctx-repo/index.html.local_backup`
- 根目录遗留的备份文件应移除

### P2-5 🟢 版本号不一致

- `.data_version` → `2.15.7`
- `version_info.txt` → `3.115.17`
- `__init__.py` 实际代码 → 无版本导出
- 容易造成混淆

### P2-6 🟢 `meshctx.yaml` 模板暴露过多字段

- 飞书 `app_secret`、微信 `corp_secret`、LINE `channel_secret` 等字段以空字符串模板暴露在公开配置中，暗示内部架构

---

## 五、安全亮点（值得肯定）

- **沙箱隔离**: `code_sandbox_v3.py` 实现了 Docker（no-network / read-only / no-new-privileges / cap-drop=ALL）+ subprocess resource limits 双重保护
- **Prompt Shield**: 77 条注入检测规则覆盖 jailbreak / SQLi / shell injection / XSS / path traversal / secret leak
- **SDB Framework**: 随机-确定性屏障提供 replay divergence 检测
- **安全头**: `X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection`, `Referrer-Policy`, `Permissions-Policy` 已配置
- **Server header 隐藏**: 自定义中间件替换 uvicorn server header
- **审批引擎**: 三级模式 (manual/smart/off) + 白名单 + 危险命令黑名单

---

## 六、修复优先级

| 优先级 | 问题 | 预计工时 |
|--------|------|---------|
| 🔴 立即 | P0-1: 轮换泄露的 DeepSeek Key | 15 min |
| 🔴 立即 | P0-2: 从 config.yaml 移除 API Key | 5 min |
| 🔴 立即 | P0-3: 从 Git 历史清除 provider_config.json | 10 min |
| 🔴 今日 | P0-4: 添加 CSRF 保护 | 2h |
| 🟡 本周 | P1-1~P1-4: CORS/cookie/rate-limit/Key 撤销 | 4h |
| 🟡 本周 | P1-5: _StubClass → 阶段 1 诊断模式 | 2h |
| 🟢 本月 | P2-1~P2-6: 零散改进 | 4h |

---

## 七、审计方法说明

本次审计为**安全焦点审计**，非全量代码审查。覆盖范围：

- ✅ 认证/授权模块完整审计 (`auth_v2.py`, `approval.py`, `permission_intel.py`)
- ✅ 安全核心模块审计 (`code_sandbox_v3.py`, `prompt_shield.py`, `sdb_framework.py`)
- ✅ API 网关 & CORS 配置 (`main.py`, `api_gateway.py`)
- ✅ 配置/密钥管理 (`config.yaml`, `meshctx.yaml`, `provider_config.json`, `.env.example`)
- ✅ 部署安全 (`Dockerfile`, `docker-compose.yml`, session 文件权限)
- ✅ 前端安全审计 (`auth.js`, `index.html` CSP, XSS 向量)
- ✅ 已有审计报告交叉验证 (AUDIT_v3.115.24, AUDIT_002, AUDIT_REPORT)
- ⚠️ 未逐文件审查: `src/core/` 下 270+ 个模块的逻辑漏洞、`tests/` 目录、`tools/` 目录、`scripts/` 目录、`docs/` 非核心文件
- ⚠️ 未审计: Windows/macOS 平台特定代码、NSIS 安装脚本、VS Code 扩展、插件模板代码

*报告由 meshctx Agent 于 2026-07-27 生成*
