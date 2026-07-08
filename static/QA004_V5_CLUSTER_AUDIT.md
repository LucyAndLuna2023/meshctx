# 🔴 004 QA — v5 集群通讯穷举审计报告

> 时间: 2026-07-08 15:57 UTC | 方法: Redis 97 key穷举 + PUBSUB逐通道审计 + 5机远程task诊断

---

## 核心结论

**不是"5台机器太多"，是 003 失控 — 9个进程在抢4个频道**

```
003 进程现状:
  hub_agent.py        x4  ← 应1个，每个都订阅 hub:inbox:003
  feishu_reply_relay  x2  ← 应1个
  feishu_hub_bridge   x1  ← OK
  hub_client listen   x2  ← 应1个
  ------------------------
  TOTAL               9个  泄漏8个
```

---

## 一、机器状态总览

| 机器 | Worker心跳 | Listener | PUBSUB inbox | PUBSUB cmd | 问题 |
|------|:--:|:--:|:--:|:--:|------|
| 001 | ✅ | 1 ✅ | 1 ✅ | 1 ✅ | 正常 |
| 002 | ✅ | 1 ✅ | 1 ✅ | 1 ✅ | 正常 |
| 003 | ✅ | 2 ⚠️ | **4 🔴** | 1 ✅ | **泄露严重** |
| 004 | ✅ | 1 ✅ | **3 🔴** | **2 🔴** | meshctx也订阅 |
| QMT | ⚠️ | ? | — | — | offline告警 |

---

## 二、P0 级问题 (3个)

### P0-1: 003 进程泄漏 (最严重)

```
hub_agent.py x4 → hub:inbox:003 有4个订阅者
feishu_reply_relay x2 → 飞书重复回复
hub_client listen x2 → 消息重复处理
```

**影响**: 每条发往003的消息被处理4次。飞书回复重复2次。资源浪费300%。

**根因**: systemd hub-agent 被手动启动覆盖，旧进程未kill。无进程监管。

**修复**: `pkill -f hub_agent; pkill -f feishu_reply_relay; kill $(pgrep -f 'hub_client.py listen' | tail -1); systemctl restart hub-agent`

### P0-2: hub:tasks 泄露 HLEN=63

admin 2026-07-07 声称"hub:tasks定期清理已在P1-1实现(>100条自动清)" — **不工作**。

- 2026-07-07: HLEN=4
- 2026-07-08: HLEN=63 (增长15.75倍/天)
- 所有 done/completed 状态从未 HDEL
- 距100阈值还有37条空间

### P0-3: hub:alerts + hub:logs 双饱和

| Key | LLEN | MAX | 饱和 | 内容 |
|-----|:---:|:---:|:---:|------|
| hub:alerts | 100 | 100 | 🔴 | "OFFLINE QMT" x N |
| hub:logs | 500 | 500 | 🔴 | heartbeat日志 |

- 无去重: 同告警每30秒重复
- 无TTL: 永不清理
- 新告警/日志被丢弃

---

## 三、P1 级问题 (4个)

### P1-1: hub:memory:versions:004 损坏

```json
{"error": "query failed: no such table: facts", "fact_count": 0}
```
004的facts表不存在。memory同步对004不可用。

### P1-2: Redis key 名污染 (未修复)

```
hub:profile_state:请把审计报告内容直接发给我: cat ~:004
```
消息正文作为Redis key名，持续被更新到15:40 UTC。输入验证缺失。

### P1-3: 伪 profile 状态追踪

`_templates` 不是合法profile，但有4条state持续更新。`002` (machine_id) 被当作profile名追踪3台机器。

### P1-4: 004 多订阅者

hub:inbox:004 有3个订阅者:
- hub_client listen (QA listener)
- hermes meshctx agent (也订阅了)
- 可能还有003 bridge订阅

hub:cmd:004 有2个订阅者 — 同上

---

## 四、P2/P3 问题 (4个)

| # | 问题 | 详情 |
|---|------|------|
| P2-1 | QMT-HOME离线告警计数器bug | last_seen=836838403s ≈ 9685天 |
| P2-2 | hub:archive:* 14条 | 旧存档key未清理 |
| P2-3 | hub:dedup:final-notify-test | 非hex格式的去重key污染 |
| P2-4 | hub:status:LAPTOP-A0T8M17I/hub:result:QMT-HOME | 旧机器残留 |

---

## 五、为什么"5台机器+1飞书这么多问题"？

### 根本原因链:
1. **003是核心瓶颈** — Redis宿主 + 飞书网关 + LLM推理 = 单点
2. **无进程监管** — 进程泄漏无人发现，手动启动覆盖systemd
3. **无key生命周期** — task/alert/log完成后从不清理
4. **admin修复不可信** — 声称"已清理/已加TTL"实际不工作
5. **无监控告警** — 100饱和/500饱和无主动通知

### 数据:
- 003上9个进程 vs 应有4个 (泄漏125%)
- hub:tasks 1天增长1475%
- hub:alerts/logs 100%饱和
- 3个频道多订阅者

---

## 六、修复优先级

| 优先级 | 操作 | 机器 | 工作量 |
|:---:|------|:---:|:---:|
| 🔴 P0 | kill 多余进程, 重启1个 hub-agent | 003 | 5分钟 |
| 🔴 P0 | HDEL hub:tasks done记录 | 003 | 1命令 |
| 🔴 P0 | LTRIM alerts/logs + 加TTL | 003 | 2命令 |
| 🟡 P1 | 重建004 facts表 | 004 | 10分钟 |
| 🟡 P1 | 输入验证: 过滤非ascii key名 | 003 | 代码修改 |
| 🟢 P2 | 清理archive/status垃圾key | 003 | 1命令 |
