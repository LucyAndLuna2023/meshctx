"""JSON Schema Validator — v3.09"""
import json, logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

class SchemaValidator:
    def validate(self, data: Any, schema: Dict) -> Tuple[bool, List[str]]:
        errors = []
        if schema.get("type") == "object" and isinstance(data, dict):
            for prop, prop_schema in schema.get("properties", {}).items():
                if prop in data:
                    ok, errs = self.validate(data[prop], prop_schema)
                    if not ok: errors.extend([f"{prop}.{e}" for e in errs])
                elif prop in schema.get("required", []):
                    errors.append(f"缺少必填字段: {prop}")
        elif schema.get("type") == "array" and isinstance(data, list):
            for i, item in enumerate(data):
                ok, errs = self.validate(item, schema.get("items", {}))
                if not ok: errors.extend([f"[{i}].{e}" for e in errs])
        elif schema.get("type") == "string" and not isinstance(data, str):
            errors.append(f"期望string,实际{type(data).__name__}")
        elif schema.get("type") == "number" and not isinstance(data, (int, float)):
            errors.append(f"期望number,实际{type(data).__name__}")
        
        return len(errors) == 0, errors
    
    def validate_json(self, json_str: str, schema: Dict) -> Dict:
        try:
            data = json.loads(json_str)
            ok, errors = self.validate(data, schema)
            return {"valid": ok, "errors": errors, "data": data if ok else None}
        except json.JSONDecodeError as e:
            return {"valid": False, "errors": [f"JSON解析错误: {e}"]}
    
    def get_stats(self) -> Dict:
        return {"schema_validator": "active", "supports": ["object","array","string","number"]}

_validator: Optional[SchemaValidator] = None
def get_schema_validator() -> SchemaValidator:
    global _validator
    if _validator is None: _validator = SchemaValidator()
    return _validator
