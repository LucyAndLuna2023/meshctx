# meshctx 集群通讯 v6 — 集成说明 (zcode@004/meshctx)

> 权威协议: hermes `profiles/admin/CLUSTER-COMM-V6.md` (v6 2026-08-30 + v6.1 2026-09-01)
> 本文档描述 meshctx 侧的实现、配置、用法与安全边界。
> 实现: `cluster/cluster_comm_v6.py` · 测试: `tests/test_cluster_comm_v6.py` (39 用例, FakeRedis 离线)

---

## 1. 身份 (三要素 + 多实例约定)

| 要素 | 值 | 环境变量覆盖 |
|---|---|---|
| 机器 | **004** (HCQA-YFVOARYRGY / WSL-New) | `MESHCTX_CLUSTER_MACHINE_ID` |
| Agent | **zcode** | `MESHCTX_CLUSTER_AGENT` |
| 项目 | **meshctx** | `MESHCTX_CLUSTER_PROJECT` |

> ⚠ **zcode 多实例约定 (2026-09-09)**: zcode 共 3 个对话实例, 按项目区分,
> 本实例负责 **meshctx**。所有隔离维度 (收信通道 / 去重键 / 心跳键 /
> journal / 收件箱文件) 均带项目维度; 其他 zcode 实例以
> `MESHCTX_CLUSTER_PROJECT=<各自项目>` 启动即可互不干扰。

密钥与 hub 地址与 WSL hermes `hub_client.py` 同源:
`HUB_REDIS_HOST` (默认 66.154.101.18) · `HUB_REDIS_PORT` (6379) · `HUB_REDIS_PASSWORD`/`HUB_REDIS_PW`。
注册: `zcode` 已写入 registry.json v6 的 `machines.004.profiles` (备份 `registry.json.bak_zcode_*`)。

## 2. 通道拓扑 (与 hermes listener 共存, 防消息盗窃)

```
zcode-meshctx 收信通道: hub:inbox:004:zcode:meshctx   ← 本实例独占消费
zcode 其他项目实例通道: hub:inbox:004:zcode:<项目>     ← 各实例互不干扰
hermes 机器队列:        hub:inbox:004                 ← 本模块只 LPUSH 投递, 绝不 RPOP
hermes profile 队列:    hub:profile:004:*             ← 同上, 只写不读
心跳键:                 hub:workers["004:zcode:meshctx"] ← 项目作用域, 不覆盖 hermes["004"]
去重键:                 hub:dedup:004:zcode:meshctx:{msg_id} ← 项目作用域, 三实例不互吞
归档:                   hub:archive:{profile}         ← 30 天 TTL (v6 §1.4)
journal/收件箱文件:     ~/.meshctx/web3_journal/zcode_meshctx.jsonl
                        ~/.meshctx/cluster/inbox/zcode_meshctx.jsonl
```

共存依据: hermes listener 的 drain 逻辑跳过含 `:` 的 inbox 后缀 → `hub:inbox:004:zcode`
不会被 hermes 消费; 本模块亦遵守"单通道写、不跨机器 RPOP"的 v5.1 铁律。

## 3. 协议实现清单 (与 CLUSTER-COMM-V6.md 逐条对齐)

| v6 条款 | 实现 |
|---|---|
| §1.1 项目路由 | `project_id` 字段 + `to_profile="profile:project"` 拆分; 优先级 `project_id > :后缀 > to_profile > from_profile > deepseek` |
| §1.2/§3 profile 白名单 | `validate_profile_name()`: 注册表名或 `[A-Za-z0-9_-]{1,64}`; 拒纯数字/`test`/含 `:` 空白控制符; 项目名放宽 (≤128, 禁路由分隔符) |
| §1.3 订阅白名单 | 本模块只订阅自己的 `hub:inbox:004:zcode` |
| §1.4 归档 TTL | `_archive()` 30 天 `EXPIRE` |
| §1.5/§5 Web3 记录层 | 收发写 `src/core/web3_messaging.Web3MessagingLayer` (哈希链, `~/.meshctx/web3_journal/zcode.jsonl`), `journal_verify()` 防篡改 |
| §1.6 孤儿队列 | 不产生含 `:` 的收件人歧义 — zcode 通道为自消费专属通道 |
| v5.1 单通道铁律 | `send_dm()` 只 LPUSH+PUBLISH `hub:inbox:{target}`, 不双写 profile 通道 |
| v6.1 §8 回执路由 | `send_reply()`: to_profile=发布者 from_profile(+:project), reply_channel 优先 (数字后缀改投递机器), 禁止固定 admin |
| v6.1 §9 自杀防护 | `is_selfkill_command()`: 拒绝含 `pkill`/`killall`/`hub_client.py listen` 的任务命令 |

## 4. 用法

```bash
# 状态自检 (身份/通道/journal/防护)
python cluster/cluster_comm_v6.py selfcheck

# 心跳 (hub:workers["004:zcode"], 与 hermes 004 条目共存)
python cluster/cluster_comm_v6.py heartbeat

# 入网通告 (投递到本机 meshctx profile 收件箱, WSL listener 落盘)
python cluster/cluster_comm_v6.py announce

# 发消息: -t 目标机器  -tp profile:project  -p project_id
python cluster/cluster_comm_v6.py send -t 002 -m "构建结果 OK" -tp meshctx:meshctx

# 回执最新一条收信 (自动按 v6.1 §8 路由给发布者)
python cluster/cluster_comm_v6.py reply -m "收到"

# 读本地收件箱 / 常驻监听 / journal 校验
python cluster/cluster_comm_v6.py inbox
python cluster/cluster_comm_v6.py listen
python cluster/cluster_comm_v6.py verify
```

编程接口: `send_dm / send_reply / announce / heartbeat / poll_once / listen /
read_inbox / journal_verify / send_admin_msg` (均可注入 redis 连接, 便于测试)。

## 5. admin 文件队列互通 (选配)

WSL admin 通讯方法为文件队列 (`/tmp/admin_msgs/<profile>/*.json`, cron 每 30s
由 `admin_msg_dispatch.py` 消费)。Windows 侧互通: 设

```
MESHCTX_ADMIN_MSG_DIR=\\wsl.localhost\<发行版名>\tmp\admin_msgs
```

后 `send_admin_msg("qa", "...")` 即按 admin_msg.py 格式投递。默认关闭。

## 6. 安全边界

- 密钥来源: WSL hermes `hub_client.py` 同源默认值; 生产建议经 `HUB_REDIS_PASSWORD` 环境变量注入。
- 本模块对 hub 的写操作限于: 自专属通道投递、机器队列投递 (标准 DM 语义)、
  自心跳键、自归档键 — 不触碰 hermes 的队列/键。
- `listen()` 需手动启动, 不随 meshctx 服务自动拉起; 无任何远程命令执行能力
  (收到的消息只落盘, 不 eval/shell)。
- Redis 不可用时优雅降级: 发送返回 `{"ok": false}`, 收信返回错误标记,
  journal (哈希链) 仍本地记录 — 满足 v6 §7 "Redis 挂后可重建"。

## 7. 验证记录 (2026-09-09)

- 单元测试: 39/39 通过 (FakeRedis 离线)。
- 真实 hub 冒烟: heartbeat ok → workers 出现 `004:zcode` 且 hermes `004` 条目完好 →
  入网通告投递成功 (msg 09c48a26) → zcode 通道空查正常 → journal 哈希链 verify ok。
- 全量回归: 见 OPTIMIZATION_REPORT_v3.129.0.md §2 (3.130.0 批次沿用同口径)。
