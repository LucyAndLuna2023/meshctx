# -*- coding: utf-8 -*-
"""meshctx SMA Phase 2 — 自修复链 + 自一致投票 (Repair Chain & Self-Consistency).

自修复链 (repair chain):
  输出 → 验证器 → 失败 → 带错误反馈重试同模型 (≤max_retry) → 仍败 → 升级下一档
  → …… 直到通过 / 档位耗尽 (返回最佳候选 + 完整失败轨迹, 供上层处置)。

自一致投票 (self-consistency):
  对可结构化输出 (json/exact) N 采样取多数; 自由文本不投票 (标注未投票)。

执行体由调用方注入 (task_fn(model_id, prompt) → str), 本模块零 LLM 依赖 —
全链路可离线测试。
"""
import json
import sys
from typing import Any, Callable, Dict, List, Optional

try:
    from src.validators import (validate_response, ValidationResult,
                                validate_json_output)
except ImportError:
    from validators import (validate_response, ValidationResult,
                            validate_json_output)


def repair_prompt(original_task: str, bad_output: str,
                  feedback: str) -> str:
    """构造自修复提示词 (原任务 + 失败输出 + 校验错误清单)."""
    return (
        f"{original_task}\n\n"
        f"## 你上次 output (未通过校验)\n{bad_output[:4000]}\n\n"
        f"## 校验反馈\n{feedback}\n\n"
        "请输出**完整修正后的结果**, 不要只给差异。"
    )


def escalation_path(tier: str) -> List[str]:
    """升级路径: L0→L1→L2→(空=耗尽)。"""
    order = ["L0", "L1", "L2"]
    try:
        i = order.index(tier)
        return order[i + 1:]
    except ValueError:
        return []


def run_with_repair(task_fn: Callable[[str, str], str],
                    task: str, tier: str,
                    models: Dict[str, str],
                    checks: Optional[List[str]] = None,
                    max_retry: int = 2) -> Dict[str, Any]:
    """带自修复的执行编排。

    task_fn(model_id, prompt) → str  (调用方注入: 非流式 chat 调用/测试桩)
    返回: {ok, output, tier_used, attempts:[{model,ok,errors}], group_msg_id:None}
    """
    checks = checks or []
    attempts = []
    best = {"ok": False, "output": "", "errors": ["未执行"]}
    current_tier = tier
    path = [tier] + escalation_path(tier)

    prompt = task
    for i, t in enumerate(path):
        model = models.get(t, "")
        if not model:
            continue
        retries = max_retry if i == 0 else 1  # 升级档只试一次 (成本控制)
        for r in range(retries + 1):
            output = task_fn(model, prompt)
            results = validate_response(output, checks)
            errors = [e for vr in results if not vr.ok for e in vr.errors]
            ok = all(vr.ok for vr in results) if results else bool(output.strip())
            attempts.append({"model": model, "tier": t, "retry": r,
                             "ok": ok, "errors": errors})
            if ok:
                return {"ok": True, "output": output, "tier_used": t,
                        "attempts": attempts}
            if not best["ok"] and output:
                best = {"ok": False, "output": output,
                        "errors": errors or best["errors"]}
            prompt = repair_prompt(task, output,
                                   "\n".join(vr.to_feedback() for vr in results)
                                   or "输出为空")
    return {"ok": False, "output": best["output"], "tier_used": path[-1] if path else tier,
            "attempts": attempts, "exhausted": True}


def self_consistency_vote(candidates: List[str],
                          mode: str = "json") -> Dict[str, Any]:
    """自一致投票: N 采样取多数 (仅结构化输出; 自由文本不投票).

    json 模式: 解析后规范序列化比对 (键序不敏感); exact: 原文比对。
    平票/全不同 → no_majority (调用方决定升级或取首个并标注)。
    """
    if not candidates:
        return {"ok": False, "error": "无候选"}
    if mode == "json":
        keys = []
        for c in candidates:
            vr = validate_json_output(c)
            if vr.ok:
                keys.append(json.dumps(vr.meta["parsed"], sort_keys=True,
                                       ensure_ascii=False))
            else:
                keys.append(None)
        valid = [k for k in keys if k is not None]
        if len(valid) < max(1, len(candidates) // 2 + 1):
            return {"ok": False, "error": "可解析候选未过半", "votes": keys}
        best = max(set(valid), key=valid.count)
        if valid.count(best) <= len(valid) // 2 and len(set(valid)) > 1:
            return {"ok": False, "error": "无多数", "votes": keys}
        idx = keys.index(best)
        return {"ok": True, "output": candidates[idx],
                "agree": f"{valid.count(best)}/{len(candidates)}"}
    # exact 模式
    from collections import Counter
    cnt = Counter(candidates)
    best, n = cnt.most_common(1)[0]
    return {"ok": n > len(candidates) // 2, "output": best,
            "agree": f"{n}/{len(candidates)}"}
