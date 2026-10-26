# KNOWN_ISSUES — 仓内挂账台账 (002codex 要求可复核载体)

> 格式: 编号 | 严重度 | 状态 | 发现方 | 描述 | 证据 | 清偿版本

## KI-1 | P3 | closed | 002codex (audit v3.135.0/1)

**Benchmark Nightly 同 SHA 红** (run 38223786427, job benchmark-dry @v3.135.0 SHA b758cd9e)
- 需确认: benchmark-dry 是否与代码相关 (v3.135.0 未动 benchmark 面) 或 workflow 环境性
- **验收判据**: Nightly @新 SHA 重跑绿 (conclusion=success) 即闭账为环境性; 若红则修复后绿
- **清偿版本**: v3.135.9 (闭账口径: b758cd9e 后 benchmark 面零改动 + Nightly workflow 环境性 PyPI 超时; 002codex 指出旧闭账证据不成立 — 本版以代码面证据重开即闭)

## KI-2 | P3 | closed | 002codex (audit v3.135.2)

**SSRF redirect follow-up**: install-url 守卫已拦直连私网 (urlsplit hostname + 400),
但 redirect 链未拦 — 恶意公网 URL 302 → 私网目标时 urllib follow redirect 实际请求 LAN。
- **修法**: install-url 下载禁 redirect (httpx follow_redirects=False 或 requests allow_redirects=False)
- **验收判据**: 守门 — 公网 URL 302→私网 被拒 (4xx); 直连私网仍 400
- **清偿版本**: v3.135.9 (_NoRedirect handler: 3xx 直接 HTTPError 拒绝 + 守门 test_install_url_no_redirect)

## KI-3 | P4 | closed | 002codex (audit v3.136.3)

**v3.136.2 认证 API 仅 12/24 assets (仅 macOS 族)** — 创建 release 时 Build macOS 未完成 (12 assets 先到),
Build Windows/Linux 后到但上传至同一 release 前 release 被手动 publish (12 assets 时点)。
- **补账/澄清**: 后续 run (38432266277 macOS rerun + Win/Linux dispatch) 将 assets 补齐至 24/24
  (公开 API 可验); 流程根修 = v3.135.12 release-publish job (draft 机制) 防再犯
- **清偿版本**: v3.135.12 (pipeline 根修) / v3.136.2 (assets 补齐 24/24)

## KI-4 | P3 | open | 002codex fdb6a408 (v3.136.18 Windows build 红)

**NSIS 标准发行不含 Persian.nlf** — `!insertmacro MUI_LANGUAGE "Persian"` 直接编译失败
(Can't open language file Persian.nlf)。
- **当前处置**: Windows 安装界面 11 语言 (产品 UI 12 语言含 fa — 安装器语言与产品 UI 语言是两层)
- **清偿路径**: 下载 NSIS contrib 非官方 Persian.nlf 放入 NSIS Contrib/Language files/ (需可重复获取的 URL,
  不能靠 runner 手动放置); 或维持 11 语言安装界面 (产品 UI fa 不受影响)
- **清偿版本**: 待排期 (P3, 安装器语言与产品语言解耦)

## KI-5 | P2 | closed @ v3.136.21 已发布 | 004meshctx 自查 (v3.136.21 Linux 封装包红)

**`meshctx-linux.tar.gz` 在 v3.136.16 / v3.136.20 / v3.136.21 三个 tag 上缺失** — build-portable 全红,
stderr 被 `>/dev/null 2>&1` 吞掉只剩 `exit code 128`。
- **真因**: Linux runner 的 git 无可交互凭证回退 (mac=osxkeychain, win=manager), clone 私有仓时
  userinfo token 未被接受即走 `could not read Username` → exit 128
- **根修**: v3.136.21 — `credential.helper store` + `~/.git-credentials` + 脱敏失败日志
  (Linux 诊断日志实证: `fatal: could not read Username for 'https://github.com'`)
- **发布前必做**: 用 `workflow_dispatch` (main) 补跑 build-portable 补齐该资产, 否则 Linux 用户
  只有 .deb 源码包, 拿不到完整二进制包
- **清偿版本**: v3.136.21 已发布 (2026-10-22T07:21:55Z, release ID 420313317) — 24/24 assets 含
  meshctx-linux.tar.gz (SHA256=590638c5…, 与 002codex 独立核验一致), 三连缺位回补完成

## KI-6 | P3 | closed @ v3.136.22 | 五方审计 v3.136.21 findings (002codex/002zcode/004zcode/004meshctx, 随 .22 清偿)

1. **F1 凭证落盘卫生**: build-linux.yml 步骤尾补 `rm -f ~/.git-credentials` (runner ephemeral 但显式清理);
   远期评估 `http.extraheader` / GITHUB_TOKEN 免落盘
2. **F2 autodiscover 串行**: docstring 称"三路并发"实为顺序 await — 下版改真 `asyncio.gather` 或改注释
3. **F3 网关 SSRF**: `MESHCTX_GATEWAY_URL` 直连无 getaddrinfo 守卫 (operator env, P3) — 复用 discover 的守卫
4. **守门收编**: autodiscover 行为级 4 例 (dd36380a, tag 外) 随 .22 进发布树 (004meshctx ③ "在途")
5. **声明纪律**: 送审件描述须与代码逐字对齐 (本轮 SSRF/并发两处夸大被 004zcode 抓 P2)
6. **draft 脱钩怪癖**: GitHub draft tag_name 会漂移 untagged-* (v3.136.19/.21 两犯) — 发布前 no-drift 必查 tag_name

## KI-7 | P1 | closed @ v3.136.22 | 002codex post-publish 终验 (v3.136.21)

**publish 事件触发资产替换**: build-macos.yml `release: types: [published]` 触发器在每次
publish 后以 tag ref 重跑构建, "Upload to Release" 条件为真 → 替换已发布 release 的 12 个
macOS 资产。v3.136.19 (02:48 publish → 02:51/53 换) 与 v3.136.21 (07:21:55 publish →
07:24/28 换) 两次实证。同源码 SHA 重建 (非可复现构建), 内容来源可信但违反 publish 后
immutable 纪律 (002codex P1)。
- **根修**: v3.136.22 移除该触发器 (全 workflow 扫描唯一一处)
- **v3.136.21 处置**: 按 002codex 指示保持现状 (内部自洽 12/12), 不原地修改, 由 .22 承接
- **教训**: publish 事件的 workflow 触发面需在发版前审计 (触发器→构建→上传链路)

## 旧账 release 清理注记 (2026-10-23, 五方裁定)

- **v3.136.4**: 该版 release (untagged-082532f0…, FAIL/HOLD 版) 已于 2026-10-23 移除,
  git tag 留存可考; 内容由 v3.136.5+ 取代 (002zcode 注记条件 + 004meshctx 会签)。
- **v3.136.20**: FAIL 冻结 draft 已于 2026-10-23 移除, 裁定在五方回执链, 删 draft 不销账
  (004meshctx 口径); 其有效内容 (autodiscover) 由 v3.136.21+ 承载。
- 全量 17 draft + 1 published untagged 处置台账: docs/release_cleanup_ledger_20261023.md
- 附带发现 (412272750): tag=v3.136.8 / name=v3.136.3 历史错位 — owner 裁决不改 (publish 后
  身份面不可变, 002codex 口径), API 消费以 tag 为准; 台账: docs/release_cleanup_ledger_20261023.md

## KI-8 | P1 | closed @ v3.137.1 | Linux 安装 3001 端口冲突假成功 (002codex 实机取证)

用户装完打开 localhost:3001/ui/setup 见"邮箱+密码+创建账号" — 实为 FreeLLMAPI Docker
容器占用 3001 (非 meshctx 页面)。三缺陷: ① installer 端口检查依赖 root 可见 PID,
普通用户下 fail-open 照常提示 3001; ② CLI 端口被占仍打印"已启动"假成功;
③ cli/探针/安装器端口口径分裂 (cli 写死 3001 忽略 MESHCTX_PORT)。
- **根修**: v3.137.1 — installer 身份探测预检 (TCP+health, 不依赖 PID) + 交互/非交互
  双模式 + 端口持久化; CLI fail-fast (bind 先于 banner) + 解析链统一 + MESHCTX_PORT 回写
- **教训**: 与 KI-7 同族 — "装完可用"必须以运行时实探为准, 静态检查 (PID 可见性/环境假设)
  在真实用户环境不可靠; 行为级守门 (tests/test_install_preflight.py + test_cli_start_port_conflict.py)
  防 recurrence

### KI-8 附注 (2026-10-24 开发期自伤实证 + 终版形态)
- v3.137.4 开发中, B2 兜底模式匹配 (pgrep "meshctx|src.main|...") 实测 SIGKILL 了本机
  `hermes -p meshctx` (cmdline 含 "meshctx" 命中归属校验) — 已重启恢复。
  终版: 模式兜底整体废除, stop 只认 端口+/health 身份 双确认。
- 002codex NF/AB 项: B1-B5 全清偿见 v3.137.4; 遗留 P3 (desktop 无范围校验等) 随下版。

### KI-8 附注2 (2026-10-26, v3.137.4 终审 + v3.137.5 清偿记录)
- 002codex 终审 v3.137.4 = FAIL/B1 两实锤: ① `pkill -9 -f "meshctx-linux/meshctx"` 宽杀;
  ② "cmdline/cwd 含 meshctx" 子串归属被 foreign cwd (/tmp/.../meshctx-foreign-owned-probe)
  绕过误杀; B3 persisted .env 非数字静默回退 3001 与声明矛盾。
- v3.137.5 清偿: 三个杀块统一 _owned_check (cwd 在 ${INSTALL_DIR} 之下的前缀匹配, 宽 pkill 废除);
  persisted/env 非数字受控报错非零退出; install-mac.sh 同型同步 (004meshctx F1)。
- 遗留 P3 随下版: desktop resolve_desktop_port 无 1-65535 范围校验 (004zcode);
  cmd_stop Windows 分支 /proc 只读死代码 (004meshctx F3); F-a Windows stop health 门
  (002zcode)。行为级守门: tests/test_install_preflight_add.py (foreign 诱饵存活/owned 终止/
  persisted abc 受控报错)。
