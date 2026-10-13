# KNOWN_ISSUES — 仓内挂账台账 (002codex 要求可复核载体)

> 格式: 编号 | 严重度 | 状态 | 发现方 | 描述 | 证据 | 清偿版本

## KI-1 | P3 | open | 002codex (audit v3.135.0/1)

**Benchmark Nightly 同 SHA 红** (run 38223786427, job benchmark-dry @v3.135.0 SHA b758cd9e)
- 需确认: benchmark-dry 是否与代码相关 (v3.135.0 未动 benchmark 面) 或 workflow 环境性
- 计划: 下轮专项 — 重跑 Nightly @当前 SHA, 若绿则记环境性闭; 若红则定位

## KI-2 | P3 | open | 002codex (audit v3.135.2)

**SSRF redirect follow-up**: install-url 守卫已拦直连私网 (urlsplit hostname + 400),
但 redirect 链未拦 — 恶意公网 URL 302 → 私网目标时 urllib follow redirect 实际请求 LAN。
- 计划: 下轮 — install-url 下载禁 redirect (urlopen 不可禁 → 换 requests allow_redirects=False
  或 httpx follow_redirects=False) + 守门 (公网 URL→302 私网 → 拒绝)
