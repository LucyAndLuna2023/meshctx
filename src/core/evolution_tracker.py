"""
meshctx v3.59 — Evolution Tracker (进化追踪器)

追踪Agent能力增长:
  1. 模块数量增长
  2. 测试覆盖率变化
  3. 性能指标趋势
  4. 知识图谱增长
  5. 跨版本能力对比
"""
import logging, time, json
from pathlib import Path
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional

logger = logging.getLogger("meshctx.evolution")

@dataclass
class EvolutionSnapshot:
    version: str=""; timestamp: float=field(default_factory=time.time)
    modules: int=0; tests: int=0; test_pass: int=0
    loc: int=0; commits: int=0; days_active: int=0

class EvolutionTracker:
    def __init__(self, project_root: Optional[str]=None):
        self._root = Path(project_root) if project_root else Path(__file__).parent.parent.parent
        self._snapshots: List[EvolutionSnapshot] = []
        self._history_file = Path.home() / ".meshctx" / "evolution.json"
        self._load()
    
    def _load(self):
        if self._history_file.exists():
            try:
                data = json.loads(self._history_file.read_text())
                self._snapshots = [EvolutionSnapshot(**s) for s in data]
            except: pass
    
    def _save(self):
        self._history_file.parent.mkdir(parents=True, exist_ok=True)
        self._history_file.write_text(json.dumps([
            {"version":s.version,"timestamp":s.timestamp,"modules":s.modules,
             "tests":s.tests,"test_pass":s.test_pass,"loc":s.loc,
             "commits":s.commits,"days_active":s.days_active}
            for s in self._snapshots
        ]))
    
    def snapshot(self, version: str) -> EvolutionSnapshot:
        core = self._root / "src" / "core"
        tests = self._root / "tests"
        modules = len(list(core.glob("*.py"))) if core.exists() else 0
        test_files = len(list(tests.glob("test_*.py"))) if tests.exists() else 0
        loc = 0
        for f in core.glob("*.py"):
            try: loc += len(f.read_text().splitlines())
            except: pass
        
        snap = EvolutionSnapshot(version=version, modules=modules, 
                                  tests=test_files, loc=loc)
        self._snapshots.append(snap)
        if len(self._snapshots) > 100: self._snapshots = self._snapshots[-100:]
        self._save()
        return snap
    
    def trend(self) -> Dict:
        if len(self._snapshots) < 2: return {"status": "insufficient_data"}
        first, last = self._snapshots[0], self._snapshots[-1]
        return {
            "versions": len(self._snapshots),
            "modules": f"{first.modules}→{last.modules} (+{last.modules-first.modules})",
            "tests": f"{first.tests}→{last.tests} (+{last.tests-first.tests})",
            "loc": f"{first.loc}→{last.loc}",
            "growth_rate": f"{(last.modules-first.modules)/max(1,len(self._snapshots)):.1f} modules/version",
        }
    
    def latest(self) -> Optional[EvolutionSnapshot]:
        return self._snapshots[-1] if self._snapshots else None

_tracker = None
def get_evolution_tracker(path=None):
    global _tracker
    if _tracker is None: _tracker = EvolutionTracker(path)
    return _tracker
