"""
meshctx NotebookEdit — Jupyter Notebook 编辑工具
对标: Claude Code NotebookEdit
"""
import json, os
from pathlib import Path

def notebook_read(path: str) -> dict:
    """读取 Jupyter notebook 内容"""
    p = Path(path).expanduser()
    if not p.exists():
        return {"ok": False, "error": f"Notebook not found: {path}"}
    try:
        with open(p) as f:
            nb = json.load(f)
        cells = []
        for i, c in enumerate(nb.get("cells", [])):
            cells.append({
                "index": i,
                "type": c.get("cell_type", "code"),
                "source": "".join(c.get("source", [])),
                "outputs": len(c.get("outputs", [])),
                "execution_count": c.get("execution_count")
            })
        return {"ok": True, "path": str(p), "cells": cells, 
                "metadata": nb.get("metadata", {}),
                "nbformat": nb.get("nbformat", 4)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def notebook_edit(path: str, cell_index: int, new_source: str = None,
                  cell_type: str = None, action: str = "replace") -> dict:
    """编辑 Jupyter notebook 的 cell
    
    Args:
        action: replace | insert | delete | append | execute
    """
    p = Path(path).expanduser()
    if not p.exists():
        return {"ok": False, "error": f"Notebook not found: {path}"}
    try:
        with open(p) as f:
            nb = json.load(f)
        cells = nb.get("cells", [])
        
        if action == "replace":
            if cell_index >= len(cells):
                return {"ok": False, "error": f"Cell index {cell_index} out of range"}
            cells[cell_index]["source"] = new_source.split("\n") if new_source else []
            if cell_type:
                cells[cell_index]["cell_type"] = cell_type
        
        elif action == "insert":
            new_cell = {
                "cell_type": cell_type or "code",
                "source": new_source.split("\n") if new_source else [],
                "metadata": {}, "outputs": []
            }
            cells.insert(cell_index, new_cell)
        
        elif action == "delete":
            if cell_index >= len(cells):
                return {"ok": False, "error": f"Cell index {cell_index} out of range"}
            cells.pop(cell_index)
        
        elif action == "append":
            new_cell = {
                "cell_type": cell_type or "code",
                "source": new_source.split("\n") if new_source else [],
                "metadata": {}, "outputs": []
            }
            cells.append(new_cell)
        
        elif action == "execute":
            if cell_index >= len(cells):
                return {"ok": False, "error": f"Cell index {cell_index} out of range"}
            cell = cells[cell_index]
            import subprocess, tempfile, sys
            src = "".join(cell.get("source", []))
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as tf:
                tf.write(src)
                tmpf = tf.name
            try:
                r = subprocess.run([sys.executable, tmpf], capture_output=True, text=True, timeout=60)
                cell["outputs"] = [{
                    "output_type": "execute_result",
                    "text/plain": r.stdout[:10000] or r.stderr[:10000]
                }]
                cell["execution_count"] = cell.get("execution_count", 0) + 1
            finally:
                os.unlink(tmpf)
        
        nb["cells"] = cells
        with open(p, 'w') as f:
            json.dump(nb, f, indent=1)
        return {"ok": True, "path": str(p), "total_cells": len(cells)}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def notebook_create(path: str, kernel: str = "python3") -> dict:
    """创建新 notebook"""
    nb = {
        "nbformat": 4, "nbformat_minor": 5,
        "metadata": {"kernelspec": {"display_name": kernel, "language": "python", "name": kernel}},
        "cells": []
    }
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, 'w') as f:
        json.dump(nb, f, indent=1)
    return {"ok": True, "path": str(p)}
