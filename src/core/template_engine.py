"""Template Engine — v3.16"""
import re, logging
from pathlib import Path
from typing import Any, Dict, Optional
logger = logging.getLogger(__name__)

class TemplateEngine:
    def render(self, template: str, context: Dict) -> str:
        result = template
        for key, value in context.items():
            result = result.replace(f"{{{{{key}}}}}", str(value))
        # Handle if/else blocks
        result = re.sub(r'{%\s*if\s+(\w+)\s*%}(.*?){%\s*else\s*%}(.*?){%\s*endif\s*%}', 
                       lambda m: m.group(2) if context.get(m.group(1)) else m.group(3), result, flags=re.DOTALL)
        return result
    
    def render_file(self, path: Path, context: Dict) -> str:
        return self.render(path.read_text(), context) if path.exists() else ""
    
    def generate_boilerplate(self, project_type: str = "python", name: str = "myproject") -> Dict[str, str]:
        if project_type == "python":
            return {
                "setup.py": f"from setuptools import setup\nsetup(name='{name}', version='0.1', packages=['{name}'])",
                "README.md": f"# {name}\n\nA Python project.",
                "src/{name}/__init__.py": "__version__ = '0.1.0'",
            }
        return {}
    
    def get_stats(self) -> Dict: return {"type": "template_engine", "supports": ["variable","if_else"]}

_engine: Optional[TemplateEngine] = None
def get_template_engine() -> TemplateEngine:
    global _engine
    if _engine is None: _engine = TemplateEngine()
    return _engine
