# 004 QA 审计 — 第四轮（06:45 UTC）

## 🚨 P0: 003 pub/sub 掉线

```
hub:inbox:003 PUBSUB NUMSUB = 0  ← 掉线！
hub:cmd:003   PUBSUB NUMSUB = 0  ← 掉线！

003 worker heartbeat: 仍在更新 (06:47)  → poll thread存活
003 task执行:         正常               → poll thread工作
003 DM实时投递:       断裂               → 只能靠60s periodic drain救回
```

**影响**: 发往003的消息/命令不会实时送达，延迟最长60秒。若drain也失败则消息丢失。

## 📊 其他指标

| 指标 | 上轮(06:30) | 本轮(06:45) | 变化 |
|------|:---:|:---:|:---:|
| hub:cmd | 0 | 0 | ✅ |
| hub:tasks | 2 | 3 | +1(正常) |
| hub:alerts | 50 | 50 | — |
| hub:logs | 295 | 419 | +124(增长中) |
| hub:inbox:* orphans | 空 | 空 | ✅ |
| hub:cmd:* orphans | 空 | 空 | ✅ |
| 003 Inbox FAILED | 1/5 | 1/5 | — |
| 004 memory | broken | broken | — |
| 002 inbox subs | 4 | 3 | -1 |

## 📡 pub/sub

| Channel | Subs | 状态 |
|---------|:---:|:---:|
| hub:inbox:001 | 1 | ✅ |
| hub:inbox:002 | 3 | ✅ |
| hub:inbox:003 | **0** | ❌ P0 |
| hub:inbox:004 | 1 | ✅ |
| hub:cmd:001 | 1 | ✅ |
| hub:cmd:002 | 1 | ✅ |
| hub:cmd:003 | **0** | ❌ P0 |
| hub:cmd:004 | 1 | ✅ |

## 🏁 结论

**003 pub/sub双通道掉线 → 新P0。** 心跳还在但实时通道断了，需重启003 listener或排查pub/sub重连逻辑。
