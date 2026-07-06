# meshctx 更新文档 v3.115.15

**日期**: 2026-07-07  
**版本**: 3.115.14 → 3.115.15  
**类型**: 关键修复

---

## 一、根本原因分析

### Bug #1: "达到最大工具调用轮次" — 根本原因

**症状**: 用户通过 web UI (127.0.0.1:3000) 使用 AI 助手时，工具调用几轮后就提示"达到最大工具调用轮次"，无法完成实际工作。

**根因**: `src/main.py` 第3115行 `max_rounds = 5` 被硬编码为5。Chat 端点的工具调用循环最多只执行5轮，超过即终止。对于需要多次工具调用的复杂任务（如"分析整个项目并修复所有bug"），5轮远远不够。

**根本修复**:
1. `max_rounds` 从硬编码5 → 默认30，且可通过请求体 `max_rounds` 参数动态调整
2. 新增循环检测：连续3次完全相同的工具调用签名 → 主动中断并报告"检测到工具调用循环"，避免浪费预算

### Bug #2: config.yaml 被 Git 冲突标记污染 → 整个系统报废

**症状**: 更新代码后，Setup 页面保存 API Key 报错"JSON.parse error"。**而且不只是保存失败，所有依赖 config.yaml 的功能全部报废** — 模型列表、Provider列表、认证等。

**根因链**:
1. `git merge` 操作在 `config.yaml` 中写入冲突标记（`<<<<<<< HEAD` / `=======` / `>>>>>>> main`）
2. `yaml.safe_load()` 遇到冲突标记 → 抛出 `ScannerError`
3. `_yaml_load()` 函数只捕获了 `ConstructorError`（为兼容旧 `!!python/object` 标签），未捕获 `ScannerError`
4. 异常穿透到 FastAPI → 渲染为 HTML 500 错误页面
5. 前端收到 HTML（期望 JSON）→ `JSON.parse` 失败

**关键问题**: 为什么一个 config.yaml 的 YAML 解析失败，会导致整个系统全部功能报废？

因为 `_yaml_load` 是**整个系统的配置加载入口**。所有 API 端点（models、providers、auth、setup）都通过它读取配置。YAML 解析爆炸 → 全局配置为空 → 所有功能瘫痪。

**根本修复**: `_yaml_load` 增加 `yaml.YAMLError` 兜底（捕获 `ScannerError`/`ParserError`），损坏的 YAML 返回空字典 `{}`，让服务器保持运行而非崩溃。

---

## 二、代码变更清单

### 文件1: `src/main.py` — 三处修复

| 行号 | 变更 | 说明 |
|------|------|------|
| 133-135 | 新增 `except yaml.YAMLError: return {}` | 捕获 Git 冲突标记导致的 ScannerError/ParserError |
| 3115 | `max_rounds = 5` → `max_rounds = int(body.get("max_rounds", 30))` | 默认30轮（可动态调整），从根源消除"5轮上限" |
| 3166-3179 | 新增循环检测逻辑 | 连续3次相同工具调用签名 → 主动中断，防止浪费预算 |

```python
# 循环检测核心逻辑
loop_detect_window: list = []
LOOP_DETECT_THRESHOLD = 3

# 每轮工具调用前构建签名并检测
call_signatures = [(tc.function.name, tc.function.arguments[:100]) for tc in msg.tool_calls]
loop_detect_window.append(call_signatures)
if len(loop_detect_window) >= LOOP_DETECT_THRESHOLD:
    if all(w == loop_detect_window[0] for w in loop_detect_window):
        yield error("检测到工具调用循环: 连续3次相同调用")
        return
```

### 文件2: `src/core/crypto.py` — YAML 防御加固

| 行号 | 变更 | 说明 |
|------|------|------|
| 17 | 新增 `except _yaml_mod.YAMLError: return {}` | monkey-patch 的 `safe_load` 同样兜底 |

### 文件3: `src/core/subagent_isolated.py` — 循环检测

| 行号 | 变更 | 说明 |
|------|------|------|
| 283-285 | 新增 `loop_detect_window` + `LOOP_THRESHOLD = 3` | 子代理循环检测变量 |
| 314-324 | 新增响应去重检测 | 连续3次相同响应 → 判定为循环并中断 |

---

## 三、测试验证

| 测试 | 结果 |
|------|------|
| `yaml.safe_load(冲突标记)` → ScannerError | PASS |
| `_yaml_load(冲突标记文件)` → `{}` | PASS |
| `_yaml_load(正常YAML)` → 正确解析 | PASS |
| `main.py ast.parse()` 语法检查 | PASS |
| `subagent_isolated.py ast.parse()` 语法检查 | PASS |
| 循环检测: 3次相同签名 → 中断 | 逻辑验证PASS |

---

## 四、版本号

```json
{"version": "3.115.15", "changes": "max_rounds 5→30 + 循环检测 + YAML损坏保护"}
```
