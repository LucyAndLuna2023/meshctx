# License Clarification Notice — cluster_groups.py (v6.2 组通道)

> 生效 2026-09-22 · 版权与许可声明 · LucyAndLuna2023 (版权持有人) 出具

## 事实

1. 组通道实现 (cluster_groups.py, 约 228 行) 曾于 commit `e28ef69a` (tag v3.131.16,
   2026-09-22) 短暂出现在本开源库, 并于 `3320f64a` 迁出至私有库 **meshctx-team**。
2. Git 历史不可改写 (本库纪律: 四方审计证据链依赖完整历史), 该实现于开源库
   历史中永久可见。

## 声明

1. **版权归属**: LucyAndLuna2023 是该实现的唯一作者与版权持有人。
2. **双重许可再授权**: 作为版权持有人, LucyAndLuna2023 将该实现以
   **AGPLv3 OR Proprietary (meshctx-team 商业许可)** 双许可提供:
   - 第三方依开源库 git 历史获取的该份代码, 按 **AGPLv3** 使用、修改、分发
     (传染义务照旧) — 完全合法, 不受影响;
   - LucyAndLuna2023 保留以 **Proprietary** 许可在 meshctx-team 私有库中
     持续演进该代码 (含全部后续修改) 的完整权利 — 版权人对自己作品的
     再授权无需任何第三方同意。
3. **实质演进**: meshctx-team 中的现版本 (v6.2b 起, commit `76e4a86+`) 相对
   开源历史版本已有实质性安全演进 (成员角色持久化 / fail-closed RBAC provider /
   org 白名单 / per-recipient fanout 去重根修 — 002codex c4e40688 4×P1 修复),
   后续闭源演进持续扩大差异。
4. **历史不改写**: 本库不因此重写 git 历史 — 保持审计证据链完整是本项目的
   发布纪律 (cluster/INCIDENTS.md 铁律"提交即证据")。

## 对第三方的实际含义

| 主体 | 权利 |
|---|---|
| 开源用户 | 按 AGPLv3 使用历史可见的该份代码 (含传染义务); 无 team 后续闭源演进 |
| meshctx-team 客户 | 按 Proprietary 许可使用持续演进的组通道 (安全修复/企业 RBAC 接入) |
| 竞品 | 从 git 历史拿到的 = v6.2 首日版本 (AGPL 传染); 拿不到闭源演进与支持 |
