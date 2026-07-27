# meshctx 团队任务清单 — 从 🟡68 到 🟢85

**基准**: 综合 68/100 | 目标: 85/100  
**修复脚本**: `fix_license.py` / `test_scaffold.py`

---

## 🔴 阶段1: 立即执行 (30 分钟, +8 分)

### T1.1 许可证统一 ✅ 已完成
- [x] `pyproject.toml`: MIT → AGPL-3.0-only
- [x] `version_info.txt`: MIT → AGPLv3
- [x] `competition.md`: git merge 冲突已解决
- [x] `jinja2>=3.1.6`: pyproject 已同步

### T1.2 语法检查通过 ✅ 
- [x] 555/555 通过 （之前误报已排除）

---

## 🟡 阶段2: 本周执行 (3 天, +12 分)

### T2.1 安全模块补测试 (当前 0%)

**目标**: `auth_v2.py` / `code_sandbox_v3.py` / `prompt_shield.py` / `approval.py` / `sdb_framework.py` 达到 80% 行覆盖

```
tests/test_auth_v2.py       — 登录/登出/API Key CRUD/会话过期/无效密码
tests/test_code_sandbox.py  — Python/Bash/JS 执行/超时/危险代码拦截/Docker 模式
tests/test_prompt_shield.py — 7 类注入检测/误报率/大输入
tests/test_approval.py      — 三级模式/安全白名单/危险黑名单/YOLO 模式
tests/test_sdb_framework.py — propose→verify→commit pipeline/replay divergence
```

**模板**: 见 `test_scaffold.py`

### T2.2 CORS 收紧

`src/main.py:511-515`:
```python
# Before
allow_headers=["*"]
# After
allow_headers=["Authorization", "Content-Type", "X-Requested-With"]
```

### T2.3 Session Cookie secure flag

`src/core/auth_v2.py:196`:
```python
# After
resp.set_cookie("meshctx_session", _hash_session(),
    httponly=True, secure=True, max_age=86400, samesite="lax")
```

### T2.4 速率限制修复

`src/main.py:560-565`: 用滑动窗口替代全量 `clear()`
```python
# Replace _rate_limits.clear() with:
now = time.time()
_rate_limits = {k: v for k, v in _rate_limits.items() 
                if now - max(v) < RATE_WINDOW * 2}
```

---

## 🟢 阶段3: 本月执行 (2 周, +5 分)

### T3.1 Stub 模块评估

20 个 ≤50 行模块逐一审查:
- `hybrid_reasoning.py`(6L) — **删除** (标注 stub)
- `image_gen.py`(6L) — **删除** (标注 stub)
- `plugin_autoload.py`(6L) — **删除** (标注 stub)
- `platform_fs.py`(10L) — **删除** (标注 stub)
- 其余 16 个 → 功能补全

### T3.2 类型标注

脑区模块优先（当前 30-50% → 目标 80%）

### T3.3 测试覆盖率 12.8% → 50%

| 优先级 | 模块 | 预估测试数 |
|--------|------|-----------|
| P0 | 安全 (5 模块) | 50 |
| P1 | 脑区 (22 模块) | 100 |
| P1 | 记忆 (13 模块) | 50 |
| P2 | 自主引擎 (8 模块) | 40 |
| P2 | LLM 推理 (8 模块) | 40 |
| P3 | 其余 | 200 |

### T3.4 性能: time.sleep → asyncio.sleep

6 个文件中的阻塞调用替换:
- `agent_tasks.py:328`
- `distributed_lock.py:495/602`
- `notification_hub.py:604`
- `schedule_wakeup.py:48`
- `task_queue_v2.py:398/754`
- `hotreload.py:38`

### T3.5 README 文档

补充核心模块列表（至少覆盖 50 个模块）

---

## 📊 预期效果

| 阶段 | 累计评分 | 工时 |
|------|---------|------|
| 基线 | 68 | — |
| 阶段1 完成 | 76 | 30 min |
| 阶段2 完成 | 82 | 3 天 |
| 阶段3 完成 | **85-88** | 2 周 |

---

## 🔧 修复脚本使用

```bash
# 许可证修复
python3 fix_license.py

# 测试脚手架
python3 test_scaffold.py    # 生成测试模板文件
pytest tests/test_auth_v2.py -v
```

---

*生成时间: 2026-07-27 | meshctx Agent*
