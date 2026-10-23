# Release 清理台账 — 2026-10-23 (旧账 18 笔处置)

> 五方裁定: 002zcode PASS / 004zcode PASS / 002codex DELETE 清单 / 004meshctx 会签。
> 审计痕迹规范载体 = git tag + 五方回执链 + 本台账 + KNOWN_ISSUES + 审计报告;
> GitHub release 对象非载体。删除仅按精确 release ID, 禁按 tag/name/版本批量。

## A 类 — draft 残留 17 笔 (全删)

| # | release ID | tag 身份 | name | assets | body | 归属/异常 |
|---|---|---|---|---|---|---|
| 1 | 420259926 | untagged-52d05f4d116d6beebeaf | v3.136.20 | 22 | 268c | .20 五方 FAIL 冻结 (缺 linux 包); 裁定在回执链, draft 删不销账 |
| 2 | 417431663 | v3.136.17 | v3.136.17 | 16 | 空 | codex FAIL/HOLD |
| 3 | 416851154 | v3.136.16 | v3.136.15 | 26 | 210c(.15) | name/tag 错位 + 双份 .15 资产 |
| 4 | 417105691 | untagged-178cdb0f667f9f52c390 | v3.136.16 | 24 | 174c | codex P1 身份 FAIL |
| 5 | 416589093 | v3.136.13 | v3.136.13 | 24 | 空 | 修复在父链不含 |
| 6 | 416547206 | v3.136.12 | v3.136.12 | 24 | 空 | codex HOLD |
| 7 | 416540171 | v3.136.11 | v3.136.11 | 24 | 空 | 跳版冗余 |
| 8 | 416531919 | v3.136.10 | v3.136.10 | 24 | 空 | codex FAIL/HOLD |
| 9 | 416618317 | untagged-41cd7a3c02c442a6dfc7 | v3.136.14 | 24 | 160c | codex P1 无 tag |
| 10 | 412849549 | v3.136.7 | v3.136.7 | 24 | 空 | .8 已正发 |
| 11 | 412836924 | v3.136.6 | v3.136.6 | 24 | 空 | 同上 |
| 12 | 412802427 | v3.136.5 | v3.136.5 | 24 | 空 | 同上 |
| 13 | 412850505 | untagged-a19503d0beb730a5e0c9 | v3.136.8 | 24 | 写的 v3.135.17 | body/name/tag 三不一致 |
| 14 | 411818434 | v3.135.12 | v3.135.12 | 24 | 空 | .13 正发取代 |
| 15 | 411879783 | untagged-dd72d559d2803d570e3f | v3.136.1 | 24 | 128c | .1 已正发 (411894658) |
| 16 | 411932464 | untagged-5e788f3ab78b3cae4894 | v3.136.2 | 24 | 201c | .2 已正发 (412271603) |
| 17 | 405710444 | v3.132.4 | v3.132.4 | 24 | 空 | draft=True + published_at 并存 (僵尸态) |

## B 类 — 已发布 untagged 1 笔 (删 release, git tag 留存)

| 18 | 412492320 | untagged-082532f04b69240e7728 | v3.136.4 | 24 | 169c | published 10-14 08:38; .4 系 FAIL/HOLD 版 (CLI TOCTOU P1), 内容已被 .5+ 取代 |

## 附带 2 笔 (不删)

| ID | tag | name | 裁定 |
|---|---|---|---|
| 412272750 | v3.136.8 | v3.136.3 (错位) | **owner 裁决 (2026-10-23): 不改, 维持台账注记** — name 为历史错位, 以 tag v3.136.8 为准; 002codex "publish 后身份面不可变" 口径采纳, 不为展示层纠错开口子 (004zcode/002zcode 改 name 意见存档不采纳) |
| 412271603 | v3.136.2 | v3.136.2 | RETAIN (12 assets 系早期全量标准, 历史件) |

## 裁定回执锚点
- 004zcode: 旧账清理逐笔裁定 (18+2) — 口径精细化 + 执行保障三条件
- 002zcode: 会签 同意 附1条注记条件 (KNOWN_ISSUES 补移除注记)
- 002codex: ACK debt-cleanup-b0faf2d6, 20 目标 by-ID snapshot, 报告 002codex_07c680da_release_cleanup_verdict_20261023.md (SHA256=e726468a…), manifest 118 项全 OK
- 004meshctx: 会签 同意 + 逐 ID 处置结果回执要求 (基线: releases 182 unique / draft 17→0)
