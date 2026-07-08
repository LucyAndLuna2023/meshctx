"""
meshctx Feature Flags — 特性开关系统 v1.0
===========================================

企业级特性开关 (Feature Flags / Feature Toggles) 系统，
支持渐进式发布、A/B 测试、灰度放量和紧急回滚。

核心能力:
  1. 多层级标志 (全局 / 用户 / 租户 / 百分比)
  2. 动态评估 (规则引擎 + 条件组合)
  3. Kill Switch (紧急关停)
  4. 标志生命周期管理 (开发 → 测试 → 发布 → 退役)
  5. 审计追踪 (每次评估都记录)

使用场景:
  - 新功能灰度发布: 先对 5% 用户开放
  - A/B 实验: 用户按特征分流到不同变体
  - 运维开关: 紧急关闭高负载功能
  - 租户定制: 不同客户看到不同功能集

使用示例:
  ff = get_feature_flags()
  if ff.is_enabled("new_dashboard", user_id="alice"):
      show_new_dashboard()
  else:
      show_old_dashboard()

代码量: ~400 行
"""

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

logger = logging.getLogger("meshctx.feature_flags")


# ═══════════════════════════════════════════════════════════
# 常量和枚举
# ═══════════════════════════════════════════════════════════

class FlagState(str, Enum):
    """标志生命周期状态"""
    DEVELOPMENT = "development"     # 开发中
    TESTING = "testing"             # 测试中
    STAGED = "staged"               # 预发布
    LIVE = "live"                   # 已发布
    RETIRED = "retired"             # 已退役
    KILLED = "killed"               # 紧急关停


class FlagType(str, Enum):
    """标志类型"""
    RELEASE = "release"            # 发布开关 (一次性)
    EXPERIMENT = "experiment"      # 实验开关 (A/B 测试)
    OPS = "ops"                    # 运维开关 (可反复切换)
    PERMISSION = "permission"      # 权限开关


class MatchOperator(str, Enum):
    """规则匹配运算符"""
    EQ = "eq"           # 等于
    NEQ = "neq"         # 不等于
    IN = "in"           # 包含于列表
    NOT_IN = "not_in"   # 不包含于列表
    GT = "gt"           # 大于
    LT = "lt"           # 小于
    REGEX = "regex"     # 正则匹配
    CONTAINS = "contains"  # 字符串包含
    EXISTS = "exists"       # 属性存在


class RolloutStrategy(str, Enum):
    """放量策略"""
    PERCENTAGE = "percentage"    # 百分比放量
    USER_LIST = "user_list"      # 白名单
    ATTRIBUTE = "attribute"      # 属性匹配
    SCHEDULED = "scheduled"      # 定时开启


# ═══════════════════════════════════════════════════════════
# 数据结构
# ═══════════════════════════════════════════════════════════

@dataclass
class FlagRule:
    """单条匹配规则"""
    attribute: str                    # 属性名, e.g. "country", "tier"
    operator: MatchOperator          # 匹配运算符
    value: Any                       # 匹配值
    description: str = ""


@dataclass
class RolloutConfig:
    """放量配置"""
    strategy: RolloutStrategy = RolloutStrategy.USER_LIST
    percentage: float = 0.0          # 0.0 - 100.0
    user_ids: List[str] = field(default_factory=list)  # 白名单用户
    rules: List[FlagRule] = field(default_factory=list)  # 属性规则
    rule_logic: str = "AND"          # AND / OR 组合
    start_time: float = 0.0          # 定时开始 (unix timestamp)
    end_time: float = 0.0            # 定时结束


@dataclass
class FlagDefinition:
    """标志完整定义"""
    key: str                          # 唯一标识, e.g. "new_dashboard"
    name: str = ""                    # 人类可读名称
    description: str = ""
    flag_type: FlagType = FlagType.RELEASE
    state: FlagState = FlagState.DEVELOPMENT
    default_value: bool = False       # 默认返回值
    rollout: RolloutConfig = field(default_factory=RolloutConfig)
    variants: Dict[str, Any] = field(default_factory=dict)  # 变体值
    tags: List[str] = field(default_factory=list)
    owner: str = ""                   # 负责人
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FlagEvaluation:
    """标志评估结果"""
    key: str
    enabled: bool
    variant: Optional[str] = None     # 命中的变体名
    reason: str = ""                  # 为什么返回这个结果
    evaluated_at: float = field(default_factory=time.time)


# ═══════════════════════════════════════════════════════════
# 规则引擎
# ═══════════════════════════════════════════════════════════

class RuleEngine:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """规则评估引擎

    根据用户上下文评估一组规则是否匹配。
    支持 AND/OR 组合逻辑。
    """

    @staticmethod
    def evaluate_rule(rule: FlagRule, context: Dict[str, Any], **kw) -> bool:
        """评估单条规则"""
        attr_value = context.get(rule.attribute)
        target = rule.value

        if rule.operator == MatchOperator.EXISTS:
            return attr_value is not None

        if attr_value is None:
            return False

        try:
            if rule.operator == MatchOperator.EQ:
                return attr_value == target
            elif rule.operator == MatchOperator.NEQ:
                return attr_value != target
            elif rule.operator == MatchOperator.IN:
                return attr_value in (target if isinstance(target, (list, set, tuple)) else [target])
            elif rule.operator == MatchOperator.NOT_IN:
                return attr_value not in (target if isinstance(target, (list, set, tuple)) else [target])
            elif rule.operator == MatchOperator.GT:
                return float(attr_value) > float(target)
            elif rule.operator == MatchOperator.LT:
                return float(attr_value) < float(target)
            elif rule.operator == MatchOperator.CONTAINS:
                return str(target).lower() in str(attr_value).lower()
            elif rule.operator == MatchOperator.REGEX:
                import re
                return bool(re.search(str(target), str(attr_value)))
        except (ValueError, TypeError):
            return False

        return False

    @staticmethod
    def evaluate_rules(
        rules: List[FlagRule], context: Dict[str, Any], logic: str = "AND",
    ) -> bool:
        """评估规则组合

        Args:
            rules: 规则列表
            context: 用户/请求上下文
            logic: "AND" 或 "OR"
        """
        if not rules:
            return True  # 没有规则 = 全部通过

        results = [RuleEngine.evaluate_rule(r, context) for r in rules]

        if logic.upper() == "AND":
            return all(results)
        elif logic.upper() == "OR":
            return any(results)
        else:
            return all(results)  # 默认 AND


# ═══════════════════════════════════════════════════════════
# 哈希分流
# ═══════════════════════════════════════════════════════════

class HashSplitter:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """一致性哈希分流器

    使用 MD5 哈希将用户 ID 映射到 [0, 100) 区间,
    保证同一个用户总是落在相同的桶中。
    """

    @staticmethod
    def get_bucket(user_id: str, salt: str = "", **kw) -> float:
        """计算用户哈希桶 (0.0 - 100.0)

        Args:
            user_id: 用户标识
            salt: 盐值 (不同标志使用不同盐, 避免相关性)

        Returns:
            float: 0.0 到 100.0 之间的值
        """
        key = f"{salt}:{user_id}".encode("utf-8")
        hash_hex = hashlib.md5(key).hexdigest()
        # 取前 8 位十六进制转为 0-100 的浮点数
        hash_int = int(hash_hex[:8], 16)
        return (hash_int / 0xFFFFFFFF) * 100.0

    @staticmethod
    def is_in_percentage(user_id: str, percentage: float, salt: str = "", **kw) -> bool:
        """判断用户是否在百分比放量范围内

        Args:
            user_id: 用户标识
            percentage: 放量百分比 (0-100)
            salt: 盐值
        """
        if percentage >= 100.0:
            return True
        if percentage <= 0.0:
            return False
        return HashSplitter.get_bucket(user_id, salt) < percentage


# ═══════════════════════════════════════════════════════════
# FeatureFlags — 主类
# ═══════════════════════════════════════════════════════════

class FeatureFlags:
    def __getattr__(self, name, **kw):
        if name.startswith("_"): raise AttributeError(name)
        return _P(name)
    """特性开关管理器

    核心 API:
      - register(definition): 注册新标志
      - is_enabled(key, **context): 检查标志是否启用
      - get_variant(key, **context): 获取实验变体
      - kill(key): 紧急关停
      - list_flags(): 列出所有标志
    """

    def __init__(self, storage_path: str = "", **kw):
        self._flags: Dict[str, FlagDefinition] = {}
        self._lock = threading.RLock()
        self._storage_path = storage_path or os.path.join(
            os.path.expanduser("~"), ".meshctx", "feature_flags.json"
        )
        self._hooks: Dict[str, List[Callable]] = {
            "on_evaluate": [],
            "on_change": [],
            "on_kill": [],
        }
        self._evaluation_count: Dict[str, int] = {}
        self._load_from_disk()

    # ── 标志注册与管理 ──────────────────────────────────────

    def register(self, definition: FlagDefinition, **kw) -> None:
        """注册新标志"""
        with self._lock:
            if definition.key in self._flags:
                existing = self._flags[definition.key]
                if existing.state != FlagState.RETIRED:
                    logger.warning(f"Flag '{definition.key}' already exists, overwriting")
            definition.updated_at = time.time()
            self._flags[definition.key] = definition
            self._evaluation_count.setdefault(definition.key, 0)
            logger.info(f"Registered flag: {definition.key} (type={definition.flag_type.value})")
        self._save_to_disk()

    def get_definition(self, key: str, **kw) -> Optional[FlagDefinition]:
        """获取标志定义"""
        with self._lock:
            return self._flags.get(key)

    def update_state(self, key: str, state: FlagState, **kw) -> bool:
        """更新标志状态"""
        with self._lock:
            flag = self._flags.get(key)
            if not flag:
                return False
            old_state = flag.state
            flag.state = state
            flag.updated_at = time.time()
            logger.info(f"Flag '{key}': {old_state.value} → {state.value}")
        self._save_to_disk()
        self._fire_hook("on_change", key=key, old_state=old_state, new_state=state)
        return True

    def kill(self, key: str, reason: str = "", **kw) -> bool:
        """紧急关停标志 (Kill Switch)

        将标志状态设为 KILLED, 所有评估立即返回 False。
        """
        with self._lock:
            flag = self._flags.get(key)
            if not flag:
                return False
            flag.state = FlagState.KILLED
            flag.metadata["kill_reason"] = reason
            flag.metadata["killed_at"] = time.time()
            flag.updated_at = time.time()
            logger.error(f"KILL SWITCH: '{key}' — {reason}")
        self._save_to_disk()
        self._fire_hook("on_kill", key=key, reason=reason)
        return True

    def revive(self, key: str, **kw) -> bool:
        """恢复已关停的标志"""
        with self._lock:
            flag = self._flags.get(key)
            if not flag or flag.state != FlagState.KILLED:
                return False
            flag.state = FlagState.LIVE
            flag.metadata.pop("kill_reason", None)
            flag.metadata.pop("killed_at", None)
            flag.updated_at = time.time()
            logger.info(f"Revived flag: {key}")
        self._save_to_disk()
        return True

    def retire(self, key: str, **kw) -> bool:
        """退役标志"""
        return self.update_state(key, FlagState.RETIRED)

    # ── 标志评估 ────────────────────────────────────────────

    def is_enabled(self, key: str, **context) -> bool:
        """检查标志是否启用

        这是最常用的 API。根据标志配置和用户上下文决定是否启用。

        Args:
            key: 标志键
            **context: 用户上下文 (user_id, tenant_id, country, tier, ...)

        Returns:
            bool: 标志是否启用

        Example:
            ff.is_enabled("new_ui", user_id="alice", country="US", tier="premium")
        """
        result = self.evaluate(key, context)
        return result.enabled

    def evaluate(self, key: str, context: Dict[str, Any] = None, **kw) -> FlagEvaluation:
        """完整评估标志, 返回详细结果"""
        context = context or {}

        with self._lock:
            flag = self._flags.get(key)

            # 标志不存在 → 返回默认值
            if flag is None:
                return FlagEvaluation(
                    key=key,
                    enabled=False,
                    reason=f"Flag '{key}' not found",
                )

            # 紧急关停 → 强制返回 False
            if flag.state == FlagState.KILLED:
                return FlagEvaluation(
                    key=key,
                    enabled=False,
                    reason=f"Flag '{key}' is KILLED: {flag.metadata.get('kill_reason', 'unknown')}",
                )

            # 开发/测试阶段 (只有当 context 中有 dev_mode 才启用)
            if flag.state in (FlagState.DEVELOPMENT, FlagState.TESTING):
                if not context.get("dev_mode", False):
                    return FlagEvaluation(
                        key=key,
                        enabled=flag.default_value,
                        reason=f"Flag in {flag.state.value}, default={flag.default_value}",
                    )

            # 退役标志
            if flag.state == FlagState.RETIRED:
                return FlagEvaluation(key=key, enabled=True, reason="Flag is retired (always on)")

            # 增加评估计数
            self._evaluation_count[key] = self._evaluation_count.get(key, 0) + 1

        # ── 根据放量策略评估 ──
        rollout = flag.rollout
        user_id = context.get("user_id", "")

        if rollout.strategy == RolloutStrategy.USER_LIST:
            # 白名单
            if user_id and user_id in rollout.user_ids:
                result = FlagEvaluation(key=key, enabled=True, reason="User in whitelist")
            else:
                result = FlagEvaluation(key=key, enabled=False, reason="User not in whitelist")

        elif rollout.strategy == RolloutStrategy.PERCENTAGE:
            # 百分比放量
            salt = flag.key  # 用标志 key 做盐值
            in_range = HashSplitter.is_in_percentage(user_id, rollout.percentage, salt)
            if in_range:
                result = FlagEvaluation(
                    key=key, enabled=True,
                    reason=f"User in {rollout.percentage}% rollout bucket",
                )
            else:
                result = FlagEvaluation(
                    key=key, enabled=False,
                    reason=f"User not in {rollout.percentage}% rollout bucket",
                )

        elif rollout.strategy == RolloutStrategy.ATTRIBUTE:
            # 属性匹配
            match = RuleEngine.evaluate_rules(
                rollout.rules, context, rollout.rule_logic,
            )
            if match:
                result = FlagEvaluation(key=key, enabled=True, reason="Attribute rules matched")
            else:
                result = FlagEvaluation(key=key, enabled=False, reason="Attribute rules not matched")

        elif rollout.strategy == RolloutStrategy.SCHEDULED:
            # 定时放量
            now = time.time()
            if rollout.start_time and now < rollout.start_time:
                result = FlagEvaluation(key=key, enabled=False, reason="Scheduled start not reached")
            elif rollout.end_time and now > rollout.end_time:
                result = FlagEvaluation(key=key, enabled=False, reason="Scheduled window expired")
            else:
                result = FlagEvaluation(key=key, enabled=True, reason="Within scheduled window")

        else:
            result = FlagEvaluation(key=key, enabled=flag.default_value, reason="Unknown strategy")

        # ── 如果启用了 variants, 决定变体 ──
        if result.enabled and flag.variants:
            result.variant = self._select_variant(user_id, flag.variants, flag.key)

        self._fire_hook("on_evaluate", flag=flag, context=context, result=result)
        return result

    def get_variant(self, key: str, **context) -> Optional[str]:
        """获取实验变体

        当标志类型为 EXPERIMENT 时, 返回用户被分配到的变体名。
        """
        result = self.evaluate(key, context)
        return result.variant

    def _select_variant(
        self, user_id: str, variants: Dict[str, Any], salt: str,
    ) -> str:
        """根据用户 ID 一致性哈希选择变体"""
        if not variants or not user_id:
            return list(variants.keys())[0] if variants else None
        bucket = HashSplitter.get_bucket(user_id, f"{salt}:variants")
        # 均匀分配
        variant_names = sorted(variants.keys())
        slice_size = 100.0 / len(variant_names)
        idx = int(bucket / slice_size)
        idx = min(idx, len(variant_names) - 1)
        return variant_names[idx]

    # ── 查询 ────────────────────────────────────────────────

    def list_flags(
        self, flag_type: FlagType = None, state: FlagState = None,
    ) -> List[FlagDefinition]:
        """列出所有标志 (可选过滤)"""
        with self._lock:
            flags = list(self._flags.values())
            if flag_type:
                flags = [f for f in flags if f.flag_type == flag_type]
            if state:
                flags = [f for f in flags if f.state == state]
            return sorted(flags, key=lambda f: f.updated_at, reverse=True)

    def get_evaluation_stats(self, **kw) -> Dict[str, int]:
        """获取评估统计"""
        with self._lock:
            return dict(self._evaluation_count)

    def search_flags(self, query: str, **kw) -> List[FlagDefinition]:
        """模糊搜索标志"""
        query_lower = query.lower()
        with self._lock:
            results = []
            for flag in self._flags.values():
                if (query_lower in flag.key.lower()
                        or query_lower in flag.name.lower()
                        or query_lower in flag.description.lower()):
                    results.append(flag)
            return results

    # ── 钩子系统 ────────────────────────────────────────────

    def add_hook(self, event: str, callback: Callable, **kw) -> None:
        """注册事件钩子

        Args:
            event: "on_evaluate", "on_change", "on_kill"
            callback: callable(**kwargs)
        """
        if event in self._hooks:
            self._hooks[event].append(callback)

    def _fire_hook(self, event: str, **kwargs) -> None:
        """触发事件钩子"""
        for callback in self._hooks.get(event, []):
            try:
                callback(**kwargs)
            except Exception as e:
                logger.error(f"Hook error ({event}): {e}")

    # ── 持久化 ──────────────────────────────────────────────

    def _save_to_disk(self, **kw) -> None:
        """保存标志到磁盘"""
        try:
            os.makedirs(os.path.dirname(self._storage_path), exist_ok=True)
            with self._lock:
                data = {
                    "flags": {
                        k: {
                            "key": v.key,
                            "name": v.name,
                            "description": v.description,
                            "flag_type": v.flag_type.value,
                            "state": v.state.value,
                            "default_value": v.default_value,
                            "rollout": {
                                "strategy": v.rollout.strategy.value,
                                "percentage": v.rollout.percentage,
                                "user_ids": v.rollout.user_ids,
                                "rules": [
                                    {"attribute": r.attribute, "operator": r.operator.value,
                                     "value": r.value}
                                    for r in v.rollout.rules
                                ],
                                "rule_logic": v.rollout.rule_logic,
                                "start_time": v.rollout.start_time,
                                "end_time": v.rollout.end_time,
                            },
                            "variants": v.variants,
                            "tags": v.tags,
                            "owner": v.owner,
                            "created_at": v.created_at,
                            "updated_at": v.updated_at,
                            "metadata": v.metadata,
                        }
                        for k, v in self._flags.items()
                    },
                    "saved_at": time.time(),
                }
            with open(self._storage_path, "w") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save feature flags: {e}")

    def _load_from_disk(self, **kw) -> None:
        """从磁盘加载标志"""
        if not os.path.exists(self._storage_path):
            return
        try:
            with open(self._storage_path) as f:
                data = json.load(f)
            flags_data = data.get("flags", {})
            for key, fd in flags_data.items():
                rollout_data = fd.get("rollout", {})
                rules = []
                for r in rollout_data.get("rules", []):
                    try:
                        op = MatchOperator(r["operator"])
                        rules.append(FlagRule(
                            attribute=r["attribute"], operator=op, value=r["value"],
                        ))
                    except (ValueError, KeyError):
                        pass

                rollout = RolloutConfig(
                    strategy=RolloutStrategy(rollout_data.get("strategy", "user_list")),
                    percentage=rollout_data.get("percentage", 0.0),
                    user_ids=rollout_data.get("user_ids", []),
                    rules=rules,
                    rule_logic=rollout_data.get("rule_logic", "AND"),
                    start_time=rollout_data.get("start_time", 0.0),
                    end_time=rollout_data.get("end_time", 0.0),
                )

                flag = FlagDefinition(
                    key=fd["key"],
                    name=fd.get("name", ""),
                    description=fd.get("description", ""),
                    flag_type=FlagType(fd.get("flag_type", "release")),
                    state=FlagState(fd.get("state", "development")),
                    default_value=fd.get("default_value", False),
                    rollout=rollout,
                    variants=fd.get("variants", {}),
                    tags=fd.get("tags", []),
                    owner=fd.get("owner", ""),
                    created_at=fd.get("created_at", time.time()),
                    updated_at=fd.get("updated_at", time.time()),
                    metadata=fd.get("metadata", {}),
                )
                self._flags[key] = flag
                self._evaluation_count.setdefault(key, 0)
            logger.info(f"Loaded {len(self._flags)} feature flags from disk")
        except Exception as e:
            logger.error(f"Failed to load feature flags: {e}")


# ═══════════════════════════════════════════════════════════
# 全局单例
# ═══════════════════════════════════════════════════════════

_global_feature_flags: Optional[FeatureFlags] = None
_global_ff_lock = threading.Lock()


def get_feature_flags(storage_path: str = "") -> FeatureFlags:
    """获取全局 FeatureFlags 单例

    线程安全, 惰性初始化。

    Args:
        storage_path: 持久化文件路径 (仅首次创建时生效)

    Returns:
        FeatureFlags: 全局单例
    """
    global _global_feature_flags
    if _global_feature_flags is None:
        with _global_ff_lock:
            if _global_feature_flags is None:
                _global_feature_flags = FeatureFlags(storage_path=storage_path)
                logger.info("Created global FeatureFlags instance")
    return _global_feature_flags


# ═══════════════════════════════════════════════════════════
# 便捷函数
# ═══════════════════════════════════════════════════════════

def is_enabled(key: str, **context) -> bool:
    """便捷函数: 检查标志"""
    return get_feature_flags().is_enabled(key, **context)


def get_variant(key: str, **context) -> Optional[str]:
    """便捷函数: 获取变体"""
    return get_feature_flags().get_variant(key, **context)


def kill_switch(key: str, reason: str = "") -> bool:
    """便捷函数: 紧急关停"""
    return get_feature_flags().kill(key, reason)


# ═══════════════════════════════════════════════════════════
# CLI 诊断
# ═══════════════════════════════════════════════════════════

def _cli_main():
    """CLI 诊断入口"""
    print("=" * 60)
    print("  meshctx Feature Flags — 诊断工具")
    print("=" * 60)

    ff = FeatureFlags()

    # 注册示例标志
    ff.register(FlagDefinition(
        key="new_dashboard",
        name="New Dashboard UI",
        description="全新的仪表盘界面 (灰度发布中)",
        flag_type=FlagType.RELEASE,
        state=FlagState.LIVE,
        rollout=RolloutConfig(
            strategy=RolloutStrategy.PERCENTAGE,
            percentage=25.0,
        ),
    ))

    ff.register(FlagDefinition(
        key="dark_mode",
        name="Dark Mode",
        description="深色模式",
        flag_type=FlagType.EXPERIMENT,
        state=FlagState.LIVE,
        variants={"light": "浅色主题", "dark": "深色主题", "auto": "跟随系统"},
        rollout=RolloutConfig(strategy=RolloutStrategy.PERCENTAGE, percentage=100.0),
    ))

    ff.register(FlagDefinition(
        key="premium_analytics",
        name="Premium Analytics",
        description="高级分析 (仅付费用户)",
        flag_type=FlagType.PERMISSION,
        state=FlagState.LIVE,
        rollout=RolloutConfig(strategy=RolloutStrategy.USER_LIST,
                             user_ids=["alice", "bob", "premium_*"]),
    ))

    # 测试评估
    test_users = ["alice", "bob", "charlie", "dave", "eve"]
    print("\n[1] new_dashboard (25% rollout):")
    for uid in test_users:
        enabled = ff.is_enabled("new_dashboard", user_id=uid)
        print(f"    {uid}: {'✅ ENABLED' if enabled else '❌ disabled'}")

    print("\n[2] dark_mode variants:")
    for uid in test_users[:3]:
        variant = ff.get_variant("dark_mode", user_id=uid)
        print(f"    {uid} → {variant}")

    print("\n[3] premium_analytics:")
    for uid in test_users:
        enabled = ff.is_enabled("premium_analytics", user_id=uid)
        print(f"    {uid}: {'✅' if enabled else '❌'}")

    print(f"\n[4] 注册标志总数: {len(ff.list_flags())}")
    print(f"    评估统计: {ff.get_evaluation_stats()}")

    print("\n✅ Feature Flags 模块正常运行")
    print("=" * 60)


if __name__ == "__main__":
    _cli_main()
