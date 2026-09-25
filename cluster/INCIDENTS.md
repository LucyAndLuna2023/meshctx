# MeshCtx 集群协作事故记录 (INCIDENTS)

> v6 协议本身审计 PASS（四维全过 @5f42d2d5, 44 tests），但 2026-09 下旬连续出现
> **协议纪律与监控盲区**导致的事故。本文件按"现象→根因→处置→对策"记录全部已知
> 事故，并映射到 v6.1 加固项。新事故必须追加记录，禁止只修不记。

---

## 事故总表

| # | 日期 | 事故 | 影响 | 根因分类 | 状态 |
|---|------|------|------|----------|------|
| I-1 | 09-21/22 | **空壳消息覆盖全量件**：002 首执在正规 LPUSH 全量 JSON 外，额外裸 publish 了 `hub:dm` 频道仅含 `{msg_id,to_profile}` 的通知壳；004 listener 将壳当完整信封收入（04:02:25Z），随后到达的全量件被 msg_id 去重丢弃。同型事故波及 001/bsc（60057c8d） | 审计回执全量件丢失，需人工重发 | 协议缺陷 × 操作违纪 | ✅ v6.1 已修 |
| I-2 | 09-21 | **回执误投**：zcode round44 清偿回执 ab736f1c `to_profile=codex` 却投进 002meshctx 收件箱 | 投递错位，人工归档转投 | 操作违纪（路由拼写） | ⚠️ 留痕方案 v6.1 记录，发送侧封装待做 |
| I-3 | 09-21→25 | **审计链停摆 4 天**：004zcode 送审 v3.131.8/9/10（c1809e6c/4176d770/797f1b92）无回执，4 天后才重发追问（31b5ac5b）；期间 round45 后无任何 meshctx 裁定 | 审计流水线断流，发版等待 | 监控缺失 | ⚠️ 超时告警工具挂账（见 TODO） |
| I-4 | 09-25 | **去重口径不明**（同 I-1 根因面）：收件方无法区分"已收过"与"被空壳占坑"，需全文关键词扫多路收件箱定位消息 | 排障成本高 | 协议缺陷 | ✅ v6.1 拒收留痕 rejected_malformed |
| I-6 | 09-19→25 | **发送路由键错 + 无送达确认**: deepseek@004 给 004zcode 的 7 条 quant 协作件投到 `hub:inbox:004:zcode:quant` (zcode 项目实例键), 该键无人消费, 堆积 **6 天** 直到 004quant/004zcode 排障才发现; 同期广播循环还长期使用污染键 `hub:profile:004:zcode:meshctx` (四段) | 协作断流 6 天 | 操作违纪 × 监控缺失 | ✅ v6.1d 已修 |

| I-5 | 08-16 | **listener 死亡无告警**：001geo pubsub=0（listener 已死），geo_pack 任务包投出后无人领取，人工才发现 | 任务积压 | 监控缺失 | ⚠️ 心跳看板+LLEN 告警挂账 |

## 根因分类与 v6.1 对策映射

| 根因类 | 对策 | 状态 |
|--------|------|------|
| **路由无守门**（send 键无白名单校验, 双通道断层: send_dm 只投机器通道） | `validate_route_key()` 白名单 (hub:inbox:{mid} / hub:profile:{mid}:{profile} / hub:inbox:{mid}:{agent}:{project}), send 前强制 assert; `send_dm` 升级双通道投递 (profile 主通道优先+机器兜底, 接收方 NX 去重防重复) | ✅ v6.1d 已实现 |
| **协议缺陷**（listener 无信封校验，壳占去重坑） | `envelope_valid()`：msg_id/from/from_profile/message 全非空才收；拒收走 `rejected_malformed` journal 且**不占 msg_id 去重坑** → 空壳先到不再误杀全量件 | ✅ 已实现（cluster_comm_v6.py, 守门 test_v61_* ×2） |
| **操作违纪**（裸 publish / 路由拼写） | ①发送一律走 `send_to_zcode()/send_dm()` 封装，禁止手搓裸 publish（守门：代码评审项）②收件侧 to_profile 与本实例不符时留痕计数 | 部分完成（留痕待做） |
| **监控缺失**（无回执超时、无 listener 存活告警） | ①送审/派活消息必须带 `expect_reply` 标记 + `hub_receipt_watch` 超时扫描 ②listener 心跳看板 + 队列 LLEN 阈值告警 | ⚠️ TODO（见下） |

## TODO（v6.2 候选）

- [ ] `tools/hub_receipt_watch.py`：扫 journal 中带 `expect_reply` 的发出件，>6h 无回执输出告警清单（直接消 I-3）
- [ ] 收件侧 `to_profile` 归属核对 + `misrouted` 计数（直接消 I-2 复发盲区）
- [ ] `hub:heartbeat` 看板 + `LLEN hub:inbox:*` 阈值告警（直接消 I-5）
- [ ] 集群各节点 listener 升级 v6.1：**004 已升级；002/001/003 需各自拉取**（防护是接收侧的，各节点升级各自受益；新旧 listener 互通兼容）

## 铁律追加（v6 §追加）

1. **禁止裸 publish**：任何通知/信令必须走完整信封 LPUSH+PUBLISH 封装函数；裸 publish 视为事故源行为（I-1 直接根因）。
2. **提交即证据**：跨机协作业务同仓库纪律——本地修好未提交=没修（2026-09-22 002codex FAIL/HOLD 同型教训）。
3. **送审必须带 expect_reply**：无回执跟踪的送审等于没送（I-3 直接根因）。
4. **发送键必须过 validate_route_key**：手搓通道键 = I-6 事故源；封装函数内置白名单 assert，绕过封装的手搓键一经发现按事故记档。
5. **堆积即事故**：任何通道 LLEN>0 超过 24h 视为事故主动排查，不等对方排障时发现（I-6 堆积 6 天的教训）。

---

*维护: 每起事故由发现方/责任方共同补记；v6.1 代码: `cluster/cluster_comm_v6.py::envelope_valid`；守门: `tests/test_cluster_comm_v6.py::test_v61_*`*
