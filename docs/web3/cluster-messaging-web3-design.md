# meshctx 集群通讯 Web3 化设计 — 去中心化消息记录层 (v1)

## 问题 (用户反馈)
1. **Redis 单点**：集群通讯 (inbox/broadcast/task/heartbeat) 全部挂 Redis，
   Redis 挂 → 消息乱、丢失、不可恢复
2. **无记录**：发送方 LPUSH 后无留存；归档存 Redis (LTRIM 500 条上限)，
   Redis 挂 = 归档丢；无哈希链/完整性校验 → 乱序/丢失无法察觉

## 设计目标
- **无单点**：通讯记录不依赖任何中央服务器
- **可追溯**：每条消息有不可变哈希 + 链式累积，任何节点可验证完整性
- **可恢复**：Redis 挂后可从任意存活节点的本地日志重建
- **渐进增强**：先本地 CRDT+哈希链 (零依赖)，再可选 IPFS 锚定 (有网关时)

## 架构分层

```
┌─────────────────────────────────────────────┐
│ 应用层: meshctx 团队/企业版 / Hermes Hub      │
├─────────────────────────────────────────────┤
│ 通讯层: Libp2p pubsub / 本地队列 (现有)        │
├─────────────────────────────────────────────┤
│ ★ 记录层 (本方案): CRDT 日志 + 哈希链         │
│   - 每条消息: {id, seq, prev_hash, payload}   │
│   - 链式累积 → 篡改/丢消息可检测               │
│   - 本地 append-only 文件 (JSONL)             │
│   - 可选: IPFS 每日锚定 (CID 上链/广播)       │
├─────────────────────────────────────────────┤
│ 存储: 本地文件 (主) + Redis (缓存, 可降级)     │
└─────────────────────────────────────────────┘
```

## 核心组件

### 1. HashChainLedger (哈希链账本)
```python
class HashChainLedger:
    # 每个节点一条链; 每条消息追加:
    #   entry = {seq, ts, sender, msg_id, prev_hash, payload_hash, data}
    #   prev_hash = SHA256(prev_entry) → 篡改/丢消息可检测
    def append(sender, msg_id, payload) -> entry
    def verify() -> (ok, first_bad_index)   # 完整性校验
    def export_cid() -> str                 # 每日链头哈希 (锚定用)
```

### 2. LocalJournal (本地日志)
- 每 profile 一个 `~/.meshctx/web3_journal/{profile}.jsonl`
- append-only + fsync → Redis 挂不丢
- 发送前写 journal (发送方记录)，接收后写 journal (接收方记录)

### 3. IPFSAnchor (可选 IPFS 锚定)
- 有 IPFS 网关时: 每日把 journal 打包 → 上传 IPFS → 得 CID
- 广播 CID 到所有节点 → 任一节点可验证"今天的消息没被改"
- 无网关时: 自动降级为本地哈希链 (零依赖)

### 4. P2PMessaging (Libp2p, Phase 2)
- 节点间直接 pubsub，绕过 Redis
- 离线节点重启后从 journal 重放 + 哈希链校验

## 与 meshctx 团队/企业版的集成
- team_memory.py: 每条记忆写 journal + 哈希链 (团队记忆不可篡改)
- business_plans.py: 订阅/席位变更写 journal (审计可追溯)
- hermes_connector.py: 事件桥接写 journal (跨节点事件可追溯)

## 实施阶段
- Phase 1 (本任务): HashChainLedger + LocalJournal + 集成 hermes_connector
  + 单元测试 → 零外部依赖, 立即解决"无记录/不可恢复"
- Phase 2: IPFS 锚定 + 团队/企业版 journal 接入
- Phase 3: Libp2p pubsub 真 P2P (去 Redis pub/sub)

## 验证
- 单测: 追加/篡改检测/丢消息检测/跨节点校验
- 集成: hermes 消息收发写 journal, 模拟 Redis 挂后从 journal 恢复
