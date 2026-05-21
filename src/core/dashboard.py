"""
Unified Dashboard — v2.52
━━━━━━━━━━━━━━━━━━━━━━
聚合所有v2.44→v2.51模块统计数据,单一API端点一览全局。
"""
import json
import time
from typing import Any, Dict


class UnifiedDashboard:
    """统一仪表盘 — 全模块统计一页展示"""

    @staticmethod
    def get_full_dashboard() -> Dict[str, Any]:
        """获取全部模块的统计汇总"""
        dashboard = {
            "timestamp": time.time(),
            "meshctx_version": "",
            "modules": {},
            "summary": {},
        }

        # 版本
        try:
            from src.core import __version__
            dashboard["meshctx_version"] = __version__
        except Exception:
            dashboard["meshctx_version"] = "unknown"

        # ── SDB Framework (v2.46) ──
        try:
            from .sdb_framework import get_sdb_engine
            sdb = get_sdb_engine()
            dashboard["modules"]["sdb"] = sdb.get_stats()
            dashboard["modules"]["sdb_reliability"] = sdb.get_reliability_score()
        except Exception as e:
            dashboard["modules"]["sdb"] = {"error": str(e)}

        # ── Task Progress (v2.45) ──
        try:
            from .task_progress import get_progress_engine
            tp = get_progress_engine()
            dashboard["modules"]["tasks"] = tp.get_stats()
        except Exception as e:
            dashboard["modules"]["tasks"] = {"error": str(e)}

        # ── Diff Preview (v2.44) ──
        try:
            from .diff_preview import get_diff_engine
            df = get_diff_engine()
            dashboard["modules"]["diff"] = {
                "pending_changes": len(df.get_pending()),
                "history_count": len(df.get_history(50)),
                "backup_count": len(df.list_backups()),
            }
        except Exception as e:
            dashboard["modules"]["diff"] = {"error": str(e)}

        # ── Brain Validator (v2.48) ──
        try:
            from .brain_validator import get_brain_validator
            bv = get_brain_validator()
            if bv._measurement_history:
                profile = bv._measurement_history[-1]
                dashboard["modules"]["brain"] = {
                    "overall_recovery": profile.get("overall_recovery", 0),
                    "grade": profile.get("recovery_grade", "N/A"),
                    "dimensions": profile.get("total_dimensions", 13),
                    "recovered": profile.get("dimensions_recovered", 0),
                }
            else:
                dashboard["modules"]["brain"] = {"status": "no_data_yet"}
        except Exception as e:
            dashboard["modules"]["brain"] = {"error": str(e)}

        # ── Self Modify (v2.47) ──
        try:
            from .self_modify import get_self_modify_engine
            sm = get_self_modify_engine()
            dashboard["modules"]["self_modify"] = sm.get_stats()
        except Exception as e:
            dashboard["modules"]["self_modify"] = {"error": str(e)}

        # ── Gateway LLM (v2.49) ──
        try:
            from .gateway_llm import get_gateway_llm
            gw = get_gateway_llm()
            dashboard["modules"]["gateway_llm"] = gw.get_stats()
        except Exception as e:
            dashboard["modules"]["gateway_llm"] = {"error": str(e)}

        # ── Unified Loop (v2.50) ──
        try:
            from .unified_loop import get_unified_loop
            ul = get_unified_loop()
            dashboard["modules"]["unified_loop"] = ul.get_metrics()
        except Exception as e:
            dashboard["modules"]["unified_loop"] = {"error": str(e)}

        # ── Attractor Reasoner (v2.51) ──
        try:
            from .attractor_reasoner import get_attractor_reasoner
            ar = get_attractor_reasoner()
            dashboard["modules"]["attractor"] = ar.get_stats()
        except Exception as e:
            dashboard["modules"]["attractor"] = {"error": str(e)}

        # ── 汇总 ──
        module_count = sum(1 for v in dashboard["modules"].values()
                          if "error" not in v)
        dashboard["summary"] = {
            "total_modules_available": module_count,
            "total_modules_checked": len(dashboard["modules"]),
            "modules": list(dashboard["modules"].keys()),
        }

        return dashboard


# 单例
_dashboard = UnifiedDashboard()


def get_dashboard() -> UnifiedDashboard:
    return _dashboard
