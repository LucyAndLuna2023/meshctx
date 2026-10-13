# KNOWN_ISSUES — 仓内挂账台账 (002codex 要求可复核载体)

> 格式: 编号 | 严重度 | 状态 | 发现方 | 描述 | 证据 | 清偿版本

## KI-1 | P3 | open | 002codex (audit v3.135.0/1)

**Benchmark Nightly 同 SHA 红** (run 38223786427, job benchmark-dry @v3.135.0 SHA b758cd9e)
- 需确认: benchmark-dry 是否与代码相关 (v3.135.0 未动 benchmark 面) 或 workflow 环境性
- **验收判据**: Nightly @新 SHA 重跑绿 (conclusion=success) 即闭账为环境性; 若红则修复后绿
- **清偿版本**: v3.135.6 (重跑闭账)

## KI-2 | P3 | open | 002codex (audit v3.135.2)

**SSRF redirect follow-up**: install-url 守卫已拦直连私网 (urlsplit hostname + 400),
但 redirect 链未拦 — 恶意公网 URL 302 → 私网目标时 urllib follow redirect 实际请求 LAN。
- **修法**: install-url 下载禁 redirect (httpx follow_redirects=False 或 requests allow_redirects=False)
- **验收判据**: 守门 — 公网 URL 302→私网 被拒 (4xx); 直连私网仍 400
- **清偿版本**: 待排期 (P3, 非阻断)
