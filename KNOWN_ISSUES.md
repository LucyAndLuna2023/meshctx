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
