# 004 QA 严格审计报告 — 集群通讯第二轮验证

> **审计时间**: 2026-07-07 05:00-05:30 UTC
> **审计人**: QA-004 (HCQA-YFVOARYRGY)
> **审计范围**: Redis hub:* 全量83 keys, E2E DM测试, pub/sub订阅, listener状态

---

## ✅ 确认修复 (4项)

| Bug ID | 描述 | 第一轮 | 第二轮 |
|--------|------|--------|--------|
| **B1** | `hub:inbox:qa` 孤儿队列 | LLEN=5 未消费 | **EXISTS=0** ✅ |
| **B2** | `hub:cmd:001` 孤儿LIST | LLEN=1 | **EXISTS=0** ✅ |
| **B2** | `hub:cmd:004` 孤儿LIST | LLEN=1 | **EXISTS=0** ✅ |
| **B6** | 002 双listener进程 | 2个进程 | **1个进程** ✅ |
| **B3** | `hub:feishu:dead` 飞书死信 | 20条 | **EXISTS=0** ✅ |

---

## 🚨 新发现Bug (7项)

### N0 [P0] — `hub:cmd` hash 51条永久数据泄漏

```
hub:cmd HLEN = 51
```

**根因**: `hub_client.py` L877-887 `_process_cmd_hash()` 对 `status != "new"` 的条目只 skip，从不 `HDEL`。

**影响**: 所有执行完毕的 done/failed 命令永久存留在 Redis hash 中。抽样：`machine_id=003, status=done`。51条只增不减，Redis内存持续泄漏。

**修复建议**: `_process_cmd_hash()` 中在 skip 之前或之后 `r_conn.hdel(key, cmd_key)`。

---

### N1 [P0] — 002 新cmd通道未部署

```
hub:cmd:002: EXISTS=0, TYPE=none
hub:cmd:002 PUBSUB NUMSUB=0
```

**根因**: P0修复（per-machine LIST替代hub:cmd hash）在002机器上未生效。其他三台正常：
- `hub:cmd:001` PUBSUB=1 ✅
- `hub:cmd:002` PUBSUB=**0** ❌
- `hub:cmd:003` PUBSUB=1 ✅
- `hub:cmd:004` PUBSUB=1 ✅

**影响**: 002只能靠旧 `hub:cmd` hash 轮询收命令，新通道完全不可用。命令投递到002的可靠性降低。

**修复建议**: 确保002 listener重启后正确订阅 `hub:cmd:002`。

---

### N2 — 003 Inbox持续投递失败

```
hub:profile_state:002:003    → "(Inbox FAILED 1 messages at 05:26 UTC)"
hub:profile_state:_templates:003 → "(Inbox FAILED 1 messages at 05:26 UTC)"
```

**特征**: 时间戳持续刷新（非陈旧数据），003上 profile `002` 和 `_templates` 的inbox投递一直在失败。但E2E DM 004→003 **成功**，说明admin profile到003的inbox正常，问题出在特定profile。

**修复建议**: 检查003上 profile `002` 和 `_templates` 的 `.hub_inbox` 路径权限/磁盘空间。

---

### N3 — `hub:alerts` 饱和 (LLEN=100)

```
LLEN=100（满载），内容全是 "OFFLINE WSL-Admin last_seen=NNNs"
```

**影响**: 队列满载后新告警无法写入（或被最旧告警覆盖）。

**修复建议**: 1) 修复WSL-Admin离线根因 2) 给alerts加TTL或trim机制。

---

### N4 — `hub:logs` 饱和 (LLEN=500)

```
LLEN=500（满载）
```

**影响**: 旧日志被覆盖丢弃，无法回溯。

---

### N5 — `hub:tasks` 5条不清理

```
hub:tasks HLEN=5，所有条目 status=done/failed，永不清除
```

**模式与N0相同**: task执行完毕不 HDEL。

---

### N6 — 004 memory DB 损坏

```
hub:memory:versions:004 → {"error": "query failed: no such table: facts", "fact_count": 0}
```

004的facts表不存在，memory同步对004不可用。对比002和001正常（377条fact）。

**修复建议**: 在004上重建facts表或从002同步DB。

---

### N7 — 002 DM文件落盘失败（复现）

```
004→002 DM (db45897f): Redis pub/sub在线 → task系统正常 → hub_inbox文件为空
```

002 listener.log 无error日志，属于静默失败。落盘路径可能错误或权限问题。

---

## 📡 E2E DM 通讯测试

| 路径 | msg_id | Redis | 文件落盘 | 结论 |
|------|--------|:---:|:---:|------|
| 004→001 | `a8fe94ac` | ✅ | ✅ grep命中 | **通** |
| 004→003 | `508c7c4a` | ✅ | ✅ grep命中 | **通** |
| 004→002 | `db45897f` | ✅ | ❌ result为空 | **半通** |

---

## 📊 集群全景

```
机器   hostname              workers  pub/sub  cmd通道    状态
001    MICROSO-DUTHE8K       ✅       ✅       LIST+订阅  正常
002    jason-ThinkPad-E470   ✅       ⚠️      hash only  ⚠️ N1+N7
003    Cloudcone-S6          ✅       ✅       LIST+订阅  ⚠️ N2(inbox)
004    HCQA-YFVOARYRGY       ✅       ✅       LIST+订阅  ⚠️ N6(memory)
```

---

## 🏁 结论

| 类别 | 数量 |
|------|:---:|
| 已修复 | 5 |
| P0新bug | **2** (N0, N1) |
| 其他新bug | **5** (N2-N7) |
| **合计残余** | **7** |

**admin声称"没有bug了"不成立。** 尤其是N1（002新cmd通道未部署）说明P0修复未完整铺开到全部机器。建议逐项修复后重新审计。
