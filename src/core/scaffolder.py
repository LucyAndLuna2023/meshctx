"""Project Scaffolder — v3.17"""
import logging, os
from pathlib import Path
from typing import Dict, Optional
logger = logging.getLogger(__name__)

SCAFFOLDS = {
    "python-api": {"src/__init__.py": "", "src/main.py": "from fastapi import FastAPI\napp = FastAPI()\n\n@app.get('/')\ndef root():\n    return {'hello':'world'}", 
                   "tests/test_main.py": "def test_root():\n    assert True", "requirements.txt": "fastapi\nuvicorn", "README.md": "# Python API\n\nFastAPI project."},
    "cli-tool": {"src/__init__.py": "", "src/cli.py": "import argparse\ndef main():\n    parser = argparse.ArgumentParser()\n    parser.parse_args()\n\nif __name__ == '__main__':\n    main()",
                 "setup.py": "from setuptools import setup\nsetup(name='mytool', version='0.1', entry_points={'console_scripts':['mytool=src.cli:main']})"},
    "plugin": {"__init__.py": "", "plugin.py": "class Plugin:\n    def activate(self): pass\n    def deactivate(self): pass",
               "manifest.json": '{"name":"myplugin","version":"0.1"}'},
}

class ProjectScaffolder:
    def scaffold(self, path: Path, template: str = "python-api") -> Dict:
        files = SCAFFOLDS.get(template, SCAFFOLDS["python-api"])
        created = []
        for filepath, content in files.items():
            full = path / filepath
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content)
            created.append(str(filepath))
        return {"template": template, "path": str(path), "created": len(created), "files": created}
    
    def list_templates(self) -> list: return list(SCAFFOLDS.keys())
    def get_stats(self) -> Dict: return {"templates": len(SCAFFOLDS), "names": list(SCAFFOLDS.keys())}

_scaffolder: Optional[ProjectScaffolder] = None
def get_project_scaffolder() -> ProjectScaffolder:
    global _scaffolder
    if _scaffolder is None: _scaffolder = ProjectScaffolder()
    return _scaffolder
