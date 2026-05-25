"""Import Optimizer — v3.13"""
import ast, logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
logger = logging.getLogger(__name__)

class ImportOptimizer:
    def analyze(self, filepath: Path) -> Dict:
        if not filepath.exists(): return {"error": "file not found"}
        tree = ast.parse(filepath.read_text())
        imports = []; unused = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imports.append(f"{node.module}.{alias.name}" if node.module else alias.name)
        return {"file": str(filepath), "total_imports": len(imports),
                "imports": imports[:20], "suggestion": "移除未使用的导入可减少启动时间"}
    
    def optimize_project(self, root: Path) -> Dict:
        results = []
        for f in root.rglob("*.py"):
            if f.stat().st_size < 10000:
                results.append(self.analyze(f))
        total = sum(r.get("total_imports", 0) for r in results)
        return {"files": len(results), "total_imports": total, "details": results[:5]}
    
    def get_stats(self) -> Dict: return {"mode": "import_analysis"}

_optimizer: Optional[ImportOptimizer] = None
def get_import_optimizer() -> ImportOptimizer:
    global _optimizer
    if _optimizer is None: _optimizer = ImportOptimizer()
    return _optimizer
