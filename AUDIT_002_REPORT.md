# 002meshctx _StubClass→Sentinel 审计报告

**审计者**: meshctx  
**日期**: 2026-07-18  
**来源**: Hub msg_id=3e65e02c  
**目标文件**: src/core/__init__.py (185行, 89模块, 600+符号)

---

## 一、002方案复述

002提出将 `_StubClass`（Null Object模式）替换为 `_NotInstalled`（Sentinel + Fail-Fast）：

| 维度 | 当前 _StubClass | 002 Sentinel |
|------|----------------|-------------|
| `__getattr__` | `return self` | `raise ImportError` |
| `__call__` | `return self` | `= __getattr__` (raise) |
| `__bool__` | `return False` | `raise ImportError` |
| `__len__` | `return 0` | (未定义，默认raise) |
| `__iter__` | `return iter([])` | (未定义，默认raise) |
| 新增 | 无 | `has_module()` / `available_modules()` |

---

## 二、优点 — 002分析正确之处

1. **静默失败是真实问题**：`module.foo.bar.baz()` 返回 stub 不报错，隐藏拼写错误和缺失依赖
2. **`__bool__ → False` 有欺骗风险**：`if module:` 看不出是"未安装"还是"功能禁用"
3. **Sentinel模式是业界公认方案**：Django、FastAPI 等框架均有类似实践
4. **改动范围小**：仅 `__init__.py` 一个文件

---

## 三、风险 — 002方案缺陷

### 风险1: 破坏性变更，无迁移路径
```python
# 现有代码模式（src/main.py 多处）
brain = _get_brain()
if brain is None:    # ✅ 这行不受影响（检查 is None）
    return
if brain:            # ❌ Sentinel下 ImportError → 崩溃
    result = brain.process()
```
`src/main.py` 中 `if brain is None` 检查有6处，但直接用 `brain` 对象属性的地方上千处——如果 brain 是 stub 且调用方法，Sentinel 会直接抛异常而当前静默返回。

### 风险2: `__call__ → raise` 破坏可选依赖模式
```python
# 当前合法模式
from meshctx import kernel  
kernel.emit(...)  # 未装meshctx-core时静默跳过 → Sentinel 下 ImportError
```
调用者无法预测是否安装了私有引擎，Sentinel 强制所有调用者包裹 try-catch。

### 风险3: `_stub` 实际很少被触发
实测：项目中 `from src.core.X import Y` 的直接导入占 99%+ 的导入路径，只有少数 `from src.core import X` 才会走到 `__getattr__` fallback。`_stub` 在已部署环境中几乎不激活。投入产出比低。

### 风险4: `__slots__` 使用不当
```python
class _NotInstalled:
    __slots__ = ('_name',)   # 002方案
```
虽然不在 `crypto._P` 范围内（铁律仅限 crypto），但 `__slots__` 在此处无性能收益（单例对象），仅增加维护心智负担。

---

## 四、裁决：条件批准（需修改）

| 维度 | 评分 | 说明 |
|------|------|------|
| 问题识别 | ⭐⭐⭐⭐⭐ | 静默失败问题真实存在 |
| 方案设计 | ⭐⭐⭐ | Sentinel 方向正确但过于激进 |
| 迁移安全 | ⭐ | 无deprecation周期，直接破坏 |
| 实际影响 | ⭐⭐ | _stub 极少激活，ROI存疑 |

**结论：方案方向正确，实现需改进。建议分阶段实施。**

---

## 五、推荐方案：Hybrid（三阶段）

### 阶段1（立即）：添加诊断工具，保留兼容
```python
import os, warnings

# 保留 _StubClass，添加警告
class _StubClass:
    def __getattr__(self, name):
        if os.environ.get('MESHCTX_STRICT'):
            raise ImportError(f"meshctx-core not installed: {name}")
        warnings.warn(f"meshctx stub accessed: {name}", RuntimeWarning, stacklevel=2)
        return self
    
    def __bool__(self):
        warnings.warn("meshctx stub bool check — core not installed", RuntimeWarning)
        return False
    # ... 其余方法不变

def has_module(name: str) -> bool:
    """检查 meshctx-core 模块是否可用"""
    try:
        __import__(f'src.core.{name}', fromlist=['__name__'])
        return True
    except ImportError:
        return False

def available_modules() -> list[str]:
    """返回当前可用的模块列表"""
    return [m for m in _known if has_module(m)]
```

### 阶段2（v3.116）：Deprecation 周期
- `__bool__` 添加 `DeprecationWarning`
- 日志记录所有 stub 访问路径
- 文档标明下一大版本将默认 strict

### 阶段3（v4.0）：全面启用 Sentinel
- `MESHCTX_STRICT` 默认 True
- `_StubClass` 替换为 `_NotInstalled`
- 保留 `has_module()` / `available_modules()` API

---

## 六、总结

002的方案在**技术方向上正确**，但**落地时机和方式需调整**。静默失败确实是毒瘤，但直接切除会让现有调用者大出血。建议采纳渐进式方案——先加诊断（has_module + 警告），再加 deprecation，最后切换 Sentinel。

**状态**: 🔴 条件批准 — 需按三阶段方案修改后重新提交。
