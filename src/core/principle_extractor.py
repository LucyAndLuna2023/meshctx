"""
MeshCtx Principle Extractor — 从记忆/错误中提取可执行原则
============================================================
核心能力:
1. 从错误日志、会话记忆、代码变更中提取原则
2. 原则结构化存储: {rule, check_fn, severity, tags, file_types}
3. 支持查询: 按文件类型/操作类型/标签检索相关原则
4. 集成LLM提取 + 确定性规则匹配
"""

import json, os, re, hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Optional, Callable, Any

# ── 内置原则库(从历史错误中学习) ──────────────────────

BUILTIN_PRINCIPLES = [
    {
        "id": "html-js-comma",
        "rule": "修改HTML中的JS对象(L常量)时，新增key前必须确保前一个key有逗号",
        "check": "node_check",
        "severity": "critical",
        "tags": ["html", "js", "i18n", "comma", "syntax"],
        "file_patterns": ["*.html"],
        "example_bad": 'cta_btn:"开始使用"\n        new_key:"val"',
        "example_good": 'cta_btn:"开始使用",\n        new_key:"val"',
        "auto_fix": "grep -n 'cta_btn' file | check trailing comma"
    },
    {
        "id": "py-yaml-import",
        "rule": "Python函数内使用yaml.safe_load/yaml.dump前必须import yaml",
        "check": "ast_scan",
        "severity": "critical",
        "tags": ["python", "yaml", "import", "crash"],
        "file_patterns": ["*.py"],
        "example_bad": "def foo():\n    config = yaml.safe_load(f)",
        "example_good": "def foo():\n    import yaml\n    config = yaml.safe_load(f)",
        "auto_fix": "grep -n 'yaml\\.' file | check for 'import yaml' in same function"
    },
    {
        "id": "py-fstring-backslash",
        "rule": "Python f-string表达式内不能含反斜杠(Python 3.10限制)",
        "check": "ast_scan",
        "severity": "critical",
        "tags": ["python", "fstring", "3.10", "syntax"],
        "file_patterns": ["*.py"],
        "example_bad": 'f"{drive}:\\\\{rest.replace(\'/\', \'\\\\\')}"',
        "example_good": 'win_rest=rest.replace("/","\\\\"); return f"{drive}:\\\\{win_rest}"',
        "auto_fix": "将反斜杠操作提取到变量,再放入f-string"
    },
    {
        "id": "nsi-backslash-n",
        "rule": "NSIS LangString值中必须用$\\n(单反斜杠)换行,不能用$\\\\n(双反斜杠)",
        "check": "byte_scan",
        "severity": "critical",
        "tags": ["nsis", "installer", "unicode", "garbled"],
        "file_patterns": ["*.nsi"],
        "example_bad": 'LangString FOO 1033 "...$\\\\n$\\\\n..."',
        "example_good": 'LangString FOO 1033 "...$\\n$\\n..."',
        "auto_fix": "python -c \"data=open(f,'rb').read();open(f,'wb').write(data.replace(b'\\$\\\\\\\\n',b'\\$\\\\n'))\""
    },
    {
        "id": "model-chat-no-swallow",
        "rule": "ModelClient.chat()不能try/except吞异常返回假成功",
        "check": "ast_scan",
        "severity": "critical",
        "tags": ["python", "model", "error-handling", "false-positive"],
        "file_patterns": ["*model*.py", "*registry*.py"],
        "example_bad": "try: resp=...\\n    return {...}\\nexcept: return {'content':f'[错误:{e}]'}",
        "example_good": "直接抛异常,让调用方处理",
        "auto_fix": "删除try/except,让异常自然传播"
    },
    {
        "id": "deploy-clear-pycache",
        "rule": "部署Python代码到远程后必须清除__pycache__和*.pyc",
        "check": "manual",
        "severity": "high",
        "tags": ["deploy", "python", "cache", "stale"],
        "file_patterns": ["*.py"],
        "example_bad": "scp file.py → systemctl restart (旧pyc仍生效)",
        "example_good": "scp → find -name __pycache__ -exec rm -rf {} + → systemctl restart",
        "auto_fix": "ssh remote 'find /opt/project -name __pycache__ -exec rm -rf {} +'"
    },
    {
        "id": "test-real-connection",
        "rule": "模型连接测试必须真实发API请求,不能接受假成功响应",
        "check": "manual",
        "severity": "high",
        "tags": ["testing", "model", "false-positive"],
        "file_patterns": ["*main*.py", "*test*.py"],
        "example_bad": "reg.get()成功就返回ok",
        "example_good": "检查base_url非空+真实发请求+检测错误响应内容",
        "auto_fix": ""
    },
    {
        "id": "deploy-sync-all-changed",
        "rule": "部署时必须同步所有修改过的文件(不仅是main.py)",
        "check": "manual",
        "severity": "high",
        "tags": ["deploy", "sync", "stale"],
        "file_patterns": ["*"],
        "example_bad": "只scp main.py,web_ui.py修改未同步",
        "example_good": "rsync -avz整个src/目录",
        "auto_fix": "git diff HEAD~1 --name-only | xargs rsync"
    },
]

class PrincipleExtractor:
    """原则提取器 — 从历史中学习,在行动前检查"""
    
    def __init__(self, storage_dir: Path = None):
        self.storage_dir = storage_dir or Path.home() / ".meshctx" / "principles"
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._principles: List[Dict] = []
        self._load()
    
    def _load(self):
        """加载内置+用户原则"""
        self._principles = list(BUILTIN_PRINCIPLES)
        user_file = self.storage_dir / "user_principles.json"
        if user_file.exists():
            try:
                with open(user_file) as f:
                    user = json.load(f)
                self._principles.extend(user)
            except:
                pass
    
    def _save_user(self, user_principles: List[Dict]):
        """保存用户自定义原则"""
        with open(self.storage_dir / "user_principles.json", 'w') as f:
            json.dump(user_principles, f, ensure_ascii=False, indent=2)
    
    def query(self, file_path: str = None, operation: str = None, 
              tags: List[str] = None, severity: str = None) -> List[Dict]:
        """查询相关原则"""
        results = []
        ext = Path(file_path).suffix if file_path else None
        
        for p in self._principles:
            # 按文件类型匹配
            if ext and p.get("file_patterns"):
                if not any(Path(file_path).match(pat) for pat in p["file_patterns"]):
                    continue
            
            # 按标签匹配
            if tags:
                if not any(t in p.get("tags", []) for t in tags):
                    continue
            
            # 按严重度过滤
            if severity and p.get("severity") != severity:
                continue
            
            results.append(p)
        
        return results
    
    def extract_from_error(self, error_msg: str, file_path: str = None, 
                          context: str = "") -> Optional[Dict]:
        """从错误中提取原则(LLM驱动)"""
        # 先用内置模式匹配
        patterns = [
            (r"SyntaxError.*Unexpected identifier", "html-js-comma"),
            (r"NameError.*name 'yaml' is not defined", "py-yaml-import"),
            (r"SyntaxError.*f-string.*backslash", "py-fstring-backslash"),
            (r"garbled|mojibake|乱码", "nsi-backslash-n"),
        ]
        
        for pattern, principle_id in patterns:
            if re.search(pattern, error_msg, re.IGNORECASE):
                for p in self._principles:
                    if p["id"] == principle_id:
                        return p
        
        return None
    
    def add_user_principle(self, rule: str, severity: str = "medium",
                          tags: List[str] = None, file_patterns: List[str] = None,
                          check: str = "manual", auto_fix: str = "") -> Dict:
        """添加用户自定义原则"""
        new_id = hashlib.md5(rule.encode()).hexdigest()[:12]
        principle = {
            "id": f"user-{new_id}",
            "rule": rule,
            "check": check,
            "severity": severity,
            "tags": tags or [],
            "file_patterns": file_patterns or ["*"],
            "auto_fix": auto_fix,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        
        # 保存
        user_file = self.storage_dir / "user_principles.json"
        existing = []
        if user_file.exists():
            try:
                with open(user_file) as f:
                    existing = json.load(f)
            except:
                pass
        existing.append(principle)
        self._save_user(existing)
        self._principles.append(principle)
        return principle
    
    def get_checklist(self, file_path: str, operation: str = "modify") -> List[str]:
        """获取针对特定操作的检查清单"""
        principles = self.query(file_path=file_path, operation=operation)
        checklist = []
        for p in principles:
            if p.get("auto_fix"):
                checklist.append(f"[{p['severity'].upper()}] {p['rule']}\n  修复: {p['auto_fix']}")
            else:
                checklist.append(f"[{p['severity'].upper()}] {p['rule']}")
        return checklist
    
    def list_all(self) -> List[Dict]:
        return self._principles


# ── 单例 ──
_extractor: Optional[PrincipleExtractor] = None

def get_extractor() -> PrincipleExtractor:
    global _extractor
    if _extractor is None:
        _extractor = PrincipleExtractor()
    return _extractor
