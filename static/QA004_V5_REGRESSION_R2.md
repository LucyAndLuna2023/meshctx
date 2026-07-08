# 🔴 004 QA — v5集群通讯回归审计 (Round 2)

> 2026-07-08 16:28 UTC | 审计+回归验证+E2E测试

---

## 修复现状（002 admin 第一轮）

| 指标 | 审计前 | 现在 | 状态 |
|------|:---:|:---:|:--:|
| hub_agent (003) | 4 | 2 | ⚠️ 半修 |
| feishu_reply (003) | 2 | 2 | ❌ |
| feishu_bridge (003) | 1 | **2** | 🔴 新泄漏 |
| listen (003) | 2 | 2 | ❌ |
| inbox:003 subs | 4 | 2 | ✅ |
| inbox:004 subs | 3 | 1 | ✅ |
| cmd:004 subs | 2 | 1 | ✅ |
| inbox:001 subs | 1 | 0→1 | ⚠️ 波动 |
| hub:tasks | 63 | **70** | 🔴 继续涨 |
| hub:alerts | 100 | 100 | 🔴 饱和 |
| hub:logs | 500 | 500 | 🔴 饱和 |

## E2E测试结果

| 测试 | 结果 | 说明 |
|------|:--:|------|
| 004→002 DM | ✅ | DM b08dfbfa 送达 |
| 004→003 DM | ✅ | DM 0703104f 送达 |
| 004→001 DM | ⚠️ | PUBSUB送达，LIST滞留(LLEN=1) |
| meshctx→QA DM | 🔴 | **P0 bug确认**: 先清空后过滤，消息丢失 |
| 飞书bridge模拟 | ⚠️ | 消息被消费，outbox=0，但无法确认飞书送达 |
| 飞书dead队列 | ✅ | 0条，已清理 |

## 剩余问题 (P0)

1. **meshctx P0**: hub_inbox 先清空后过滤 → source=meshctx 消息永久丢失
2. **003进程泄漏**: 5个多余进程（2 reply + 2 listen + 1 bridge新增）
3. **hub:tasks**: 70条永不清理，admin声称的自动清理不工作
4. **hub:alerts/logs**: 双饱和，无TTL/去重

## 根因分析

```
002 admin只做了 pkill hub_agent (砍2个) → 其他进程和存储层完全没碰
feishu_bridge 反而从1→2 → 可能是 systemd restart 触发了重复启动
001 listener波动 → 可能是自动重启机制在工作
```
