"""Data Export Engine — v3.10"""
import json, csv, io, logging, time
from pathlib import Path
from typing import Any, Dict, List, Optional
logger = logging.getLogger(__name__)

class DataExporter:
    def to_json(self, data: Any, path: Optional[Path] = None) -> str:
        content = json.dumps(data, indent=2, ensure_ascii=False)
        if path: path.write_text(content, encoding="utf-8")
        return content
    def to_csv(self, data: List[Dict], path: Optional[Path] = None) -> str:
        if not data: return ""
        output = io.StringIO(); w = csv.DictWriter(output, fieldnames=data[0].keys())
        w.writeheader(); w.writerows(data)
        content = output.getvalue()
        if path: path.write_text(content, encoding="utf-8")
        return content
    def to_markdown(self, data: List[Dict], path: Optional[Path] = None) -> str:
        if not data: return ""
        keys = list(data[0].keys())
        lines = ["| " + " | ".join(keys) + " |", "|" + "|".join(["---"]*len(keys)) + "|"]
        for row in data: lines.append("| " + " | ".join(str(row.get(k,"")) for k in keys) + " |")
        content = "\n".join(lines)
        if path: path.write_text(content, encoding="utf-8")
        return content
    def get_stats(self) -> Dict: return {"formats": ["json","csv","markdown"]}

_exporter: Optional[DataExporter] = None
def get_data_exporter() -> DataExporter:
    global _exporter
    if _exporter is None: _exporter = DataExporter()
    return _exporter
