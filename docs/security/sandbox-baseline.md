# MeshCtx 沙箱安全基线 (Sandbox Security Baseline)

- 文档: WP7 (MCTX-PLAN-2026-0903 P1-4)　版本: v1.0　日期: 2026-09-03
- 回应: Artifactory 型零日沙箱逃逸 / AISI"伪造身份越权"类事件 (2026-08/09 报告)

## 1. 威胁模型 (What we defend)

| 威胁 | 案例/依据 | 防线 |
|---|---|---|
| 容器内逃逸到宿主 (cgroup/命名空间提权) | OpenAI Agent Artifactory 零日 (2026-07) | cap-drop ALL + no-new-privileges + 非 root + seccomp |
| 挂载宿主敏感资源 (docker.sock / /proc / /sys) | 沙箱逃逸经典路径 | 只读 rootfs + 仅 workspace 可写 + 静态分级拒 high |
| 宿主密钥/凭据泄漏进沙箱 | env 直传是常见泄露面 | env 白名单注入, 绝不透传宿主环境 |
| 外联 C2 / 明文外传 | 恶意 agent 回传数据 | 默认 --network none (白名单端口显式开) |
| 资源耗尽 (fork 炸弹/内存) | 沙箱拖垮宿主 | --pids-limit / --memory / --cpus 限额 |

## 2. 硬化基线 (默认全开, src/core/sandbox_policy.py)

```bash
docker run --rm \
  --network none \                # 默认禁网
  --read-only \                   # 只读 rootfs
  --cap-drop ALL \                # 无 Linux capability
  --security-opt no-new-privileges \
  --pids-limit 256 --memory 512m --cpus 1.0 \
  --user 65534:65534 \            # nobody
  -v <workspace>:/workspace:rw \  # 唯一可写挂载
  <image> <command>
```

- env: 经 `env={...}` 显式白名单注入; **宿主环境变量 (API key 等) 永不透传**。
- `allow_network=True` 仅白名单端口场景显式开启 (进审批)。
- 程序化入口: `build_hardened_docker_cmd()` / `docker_run_cmd_str()`; 
  静态分级: `classify_escape_risk(script)` → high(直接拒) / medium(审批) / low(放行)。

## 3. 逃逸路径测试集 (tests/test_sandbox_policy.py, 16 passed)

高危样本 (均判 high): docker.sock 挂载 / nsenter / chroot / mount /proc / cap_add=SYS_ADMIN / unshare / ptrace
中危样本 (均判 medium): 反弹 shell /dev/tcp、nc -e、rm -rf /、明文外传
良性样本 (判 low): echo/ls/cat

## 4. 落地与 action_gate 联动

- 容器化执行路径 (未来 docker-backed 沙箱) 必须经 `build_hardened_docker_cmd` 构造;
  宿主机 subprocess 直跑 (code_sandbox_v3 默认) 为既有行为, 不受本模块影响 (加法式)。
- action_gate / 审批链对 agent 提交的 shell 先跑 `classify_escape_risk`: high 直接拒 +
  审计, medium 进审批 (与 task_cards 审批流、遥测 trace 贯通)。

## 5. 兼容与迁移 (002codex P3②)

- 若用户既有自建 docker-compose 未含上述参数: 升级 3.123.0 后按本基线补参数即可,
  breaking change 仅在"旧容器仍挂宿主机卷写/开特权"场景, 升级提示显式标注。

## 6. 未来项

- 真实 docker-backed 执行路径 (仓库当前 code_sandbox 为宿主直跑) — 列为 3.125+ 立项;
  本基线与 policy 模块先行落地, 确保届时唯一执行入口即硬化入口。
