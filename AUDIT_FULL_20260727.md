# 🔍 meshctx 全量代码审计报告 — 2026-07-27

**审计范围**: 全产品 (276 核心模块 + CLI + 网站 + 部署 + 测试 + 工具)  
**代码规模**: src/ 122,775 行 + website/ 897 行 + tests/ 206 文件 + tools/ 24 文件  
**审计方法**: 全量扫描 + 重点深入 + 批量模式检测

---

## 零、执行摘要 (Executive Summary)

meshctx 是一个 27 万行代码的大型 AI Agent 平台，整体架构完整、核心功能真实实现。但安全方面存在 **7 个严重漏洞**（含 3 个真实 API/密码泄露）和 **15 个高优先级问题**需立即处理。

**最重要的发现**: `deploy.sh` 硬编码了生产服务器 root SSH 密码，这是**最高级别的安全事件**。

---

## 一、🔴 P0 — 严重安全漏洞

| # | 问题 | 位置 | 风险 |
|---|------|------|------|
| P0-1 | **`deploy.sh` 硬编码 root SSH 密码** | `deploy.sh:15` | 🔴 极危 |
| P0-2 | **Session 文件泄露 2 个 DeepSeek API Key** | `.meshctx/sessions/*.presanitize` | 🔴 极危 |
| P0-3 | **`config.yaml` 含真实 API Key** | `config.yaml:6` | 🔴 高危 |
| P0-4 | **`provider_config.json` 未被 .gitignore 排除** | `provider_config.json` | 🔴 高危 |
| P0-5 | **无 CSRF 保护** | `auth_v2.py` 所有认证端点 | 🔴 高危 |
| P0-6 | **`crypto.py` YAML unsafe deserialization** | `crypto.py:15` | 🔴 高危 |
| P0-7 | **`llm_code_engine.py` `shell=True` 注入风险** | `llm_code_engine.py:185` | 🔴 中危 |

---

## 二、🔴 P0 详细分析

### P0-1 🔴 `deploy.sh` 硬编码 root SSH 密码 — 极危

```bash
# deploy.sh:15
PASSWORD="LucyAndLuna@2023"
SERVER="47.120.0.239"
REMOTE_USER="root"
```

- **影响**: 任何能读取仓库的人可直接以 root 身份 SSH 到阿里云生产服务器 `47.120.0.239`
- **修复**: 立即轮换服务器密码；从 Git 历史删除 `deploy.sh`；改用 SSH key + `.gitignore`
- **状态**: 🔴 未修复

### P0-2 🔴 Session 文件泄露真实 API Key — 极危

- **位置**: `/home/jason/.meshctx/sessions/` 下 6+ 个 `.presanitize` 文件
- **Key 1**: `sk-9af61995b6274f218f29a1ec31eac06f` (DeepSeek)
- **Key 2**: `sk-adc7bcd066cd4f4781280c6955a1dcf4` (DeepSeek)
- **文件权限**: 664 (world-readable)
- **修复**: 立即在 DeepSeek 控制台轮换；删除 `.presanitize` 文件；session 目录 `chmod 700`；实现 session 序列化密钥脱敏

### P0-3 🔴 `config.yaml` 含 API Key

```yaml
# config.yaml:6
key: enc:sk-b6c...613f
```
- `enc:` 前缀并非真实加密，只是字符串标记
- **修复**: 用 `${DEEPSEEK_API_KEY}` 环境变量替代

### P0-4 🔴 `provider_config.json` 未被 Git 排除

- `.gitignore` 第 36 行写了但文件仍在仓库中
- 内容: `{"openai": {"key": "sk-openai-browser", ...}}`
- **修复**: `git rm --cached provider_config.json`

### P0-5 🔴 无 CSRF 保护

- `/api/auth/login`、`/api/auth/logout`、`/api/auth/keys` 无 CSRF token
- 攻击者可构造恶意页面诱使管理员执行 API Key 增删操作
- **修复**: 添加 CSRF 中间件

### P0-6 🔴 `crypto.py` YAML Unsafe Deserialization

```python
# crypto.py:11-16
_original_safe_load = _yaml_mod.safe_load
def _patched_safe_load(stream):
    try:
        return _original_safe_load(stream)
    except _yaml_mod.constructor.ConstructorError:
        return _yaml_mod.load(stream, Loader=_yaml_mod.Loader)  # ❌ unsafe!
_yaml_mod.safe_load = _patched_safe_load
```

- **影响**: 全局 monkey-patch `yaml.safe_load()`，遇到解析错误时退化为 `yaml.load()`，可执行任意 Python 代码（`!!python/object` 标签）
- **注意**: 注释提到 "legacy !!python/object YAML tag compatibility"，但牺牲安全性来换兼容性
- **修复**: 移除该 monkey-patch，或使用 `yaml.SafeLoader` 扩展自定义构造器

### P0-7 🔴 `llm_code_engine.py` Shell 注入风险

```python
# llm_code_engine.py:185
r = subprocess.run(
    f"git diff {base}..{head} --stat && echo '---' && git diff {base}..{head} -- ...",
    shell=True, ...  # ❌ 用户可能控制的 branch 名未转义
)
```

- **影响**: 若 `base` 或 `head` 来自用户输入，可注入任意命令
- **修复**: 使用列表参数形式 `["git", "diff", f"{base}..{head}"]` 替代 `shell=True`

---

## 三、🟡 P1 — 高优先级问题

| # | 问题 | 位置 |
|---|------|------|
| P1-1 | CORS `allow_headers=["*"]` + `allow_credentials=True` | `main.py:511-515` |
| P1-2 | Session cookie 缺少 `secure` flag | `auth_v2.py:196` |
| P1-3 | 速率限制 5 分钟全量清空（绕过容易） | `main.py:560-565` |
| P1-4 | API Key 撤销仅按 SHA256 前 12 位 hex 匹配 | `auth_v2.py:252` |
| P1-5 | `_StubClass` 静默失败（002 审计修复未落地） | `core/__init__.py` |
| P1-6 | `monitor.py` `shell=True` 执行用户命令 | `monitor.py:45` |
| P1-7 | `desktop_agent.py` `shell=True` 无输入验证 | `desktop_agent.py:82` |
| P1-8 | `tools/setup_build_env.py` 硬编码凭据 | `tools/setup_build_env.py:3` |
| P1-9 | `tools/bore_auth_test.py` 密码暴力破解工具 | `tools/bore_auth_test.py` |
| P1-10 | VS Code 扩展 `dashboard` endpoint HTML 直接渲染 | `vscode/src/extension.ts` |
| P1-11 | Dockerfile 以 root 运行容器 | `Dockerfile` |
| P1-12 | `sandbox.py` `safe_load` 退化为 `yaml.load()` | 同 P0-6（全局 monkey-patch 影响 sandbox） |
| P1-13 | `code_benchmark.py` 直接 `exec(code, namespace)` | `code_benchmark.py:131` |
| P1-14 | `swarm_codegen.py` 直接 `exec(full, namespace)` | `swarm_codegen.py:229` |
| P1-15 | `sandbox.py` 旧版 `exec()` / `eval()` + `shell=True` | `sandbox.py:364,574,694,911` |

---

## 四、🟢 P2 — 中低优先级问题

| # | 问题 | 位置 |
|---|------|------|
| P2-1 | 密码强度视觉与实际验证不一致 (R8#53) | `auth.js` |
| P2-2 | `changePassword` 不调用 `isPasswordStrong` (R8#54) | `auth.js` |
| P2-3 | Auth token 存 localStorage (已知 XSS 风险) | `auth.js:132` |
| P2-4 | `index.html.local_backup` 遗留文件 | 仓库根目录 |
| P2-5 | 版本号不一致 (2.15.7 vs 3.115.17 vs 3.33.0) | `.data_version` / `version_info.txt` / `pyproject.toml` |
| P2-6 | `meshctx.yaml` 模板暴露过多内部架构字段 | `meshctx.yaml` |
| P2-7 | 20 个小型模块疑似 stub (6-50 行) | `src/core/` (见附表) |
| P2-8 | `info_geometric_router.py` 1 个 `NotImplementedError` | `info_geometric_router.py:496` |
| P2-9 | `code_sandbox_v3.py` Go 不支持 subprocess 模式 | `code_sandbox_v3.py` |
| P2-10 | 16 处裸 `except:` 块 | 分布在 6 个文件中 |
| P2-11 | `__import__()` 动态导入无错误处理 | `core/__init__.py:199-265` |
| P2-12 | `brain_router.py` 依赖 `numpy` 引入 | `brain_router.py:2` 等 |
| P2-13 | 测试文件仅有 `assert` 无测试框架结构化断言 | `tests/` |
| P2-14 | `meshctx_setup.nsi` 版本号硬编码 3.115.16 | NSIS 安装脚本 |
| P2-15 | `pyproject.toml` 声明 MIT license 但仓库是 MIT | 许可证不一致 |

---

## 五、安全亮点

- ✅ `code_sandbox_v3.py`: Docker 双重隔离 (no-network/read-only/no-new-privileges/cap-drop=ALL/pids-limit) + subprocess resource limits
- ✅ `prompt_shield.py`: 77 条注入检测规则 (jailbreak/SQLi/shell/XSS/path traversal/secret leak)
- ✅ `secret_scanner.py`: 702 行完整实现，30+ 正则检测 7 大类密钥泄露
- ✅ `security_scanner.py`: AST 级别代码漏洞扫描
- ✅ `crypto.py`: Fernet 对称加密 API Key，`.meshctx/.fernet_key` 权限 600
- ✅ 安全响应头: X-Content-Type-Options / X-Frame-Options / X-XSS-Protection / Referrer-Policy / Permissions-Policy
- ✅ Server header 隐藏
- ✅ 审批引擎三级模式
- ✅ SDB Framework 随机-确定性屏障

---

## 六、模块审计统计

| 类别 | 总数 | 真实实现 | 疑似 Stub | 含安全问题 |
|------|------|---------|-----------|-----------|
| 核心引擎 | 276 | 256 | 20 | 8 |
| 脑区模块 | 21 | 21 | 0 | 0 |
| 测试文件 | 206 | 196 (有断言) | 10 (空) | — |
| 工具脚本 | 24 | 24 | 0 | 6 |
| 前端文件 | 37 | 37 | 0 | 4 |

**疑似 Stub 模块 (≤50 行)**:
`hybrid_reasoning.py(6)`, `image_gen.py(6)`, `plugin_autoload.py(6)`, `platform_fs.py(10)`, `dashboard.py(15)`, `healer.py(16)`, `win_admin.py(27)`, `websocket_plugin.py(30)`, `action_gate.py(33)`, `telegram_router.py(35)`, `tts.py(35)`, `global_workspace.py(38)`, `watchdog.py(40)`, `acp_server.py(41)`, `principle_extractor.py(42)`, `federated.py(44)`, `auto_deploy.py(45)`, `active_inference.py(46)`, `knowledge_transfer.py(48)`, `performance.py(49)`

---

## 七、修复优先级时间线

### 🔴 立即（今天）
1. P0-1: 轮换 `47.120.0.239` root 密码，`git rm deploy.sh`
2. P0-2: 轮换 DeepSeek API Key，删除 `.presanitize` 文件
3. P0-3: 从 `config.yaml` 移除 API Key
4. P0-4: `git rm --cached provider_config.json`

### 🔴 今日
5. P0-6: 移除 `crypto.py` YAML 不安全回退
6. P0-7: 修复 `llm_code_engine.py` shell 注入

### 🟡 本周
7. P0-5: 添加 CSRF 保护
8. P1-1~P1-4: CORS/cookie/rate-limit/Key 撤销优化
9. P1-6/P1-7: 审计 monitor/desktop_agent shell 使用
10. P1-8/P1-9: 清理 tools/ 中的敏感凭据

### 🟢 本月
11. P1-5: _StubClass 阶段 1 改造
12. P1-11: Dockerfile 非 root 用户
13. P2-3: localStorage → httpOnly cookie 迁移
14. P2-5: 统一版本号
15. P2-7: 20 个 stub 模块评估（实现或标记）

---

*审计完成时间: 2026-07-27 | 审计工具: meshctx Agent | 报告版本: v1.0*
