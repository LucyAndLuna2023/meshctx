"""
meshctx 自防御系统 — Agent Governance Engine
加载AGENTS.md规则 + 预提交门禁 + 错误模式学习 + 发布闸门
"""
import os, re, json, subprocess, sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

class AgentGovernance:
    """AI Agent的自防御治理引擎 — 借鉴Claude Code的AGENTS.md + pre-commit体系"""
    
    def __init__(self, project_root: Path = None):
        self.root = project_root or Path(__file__).resolve().parent.parent
        self.rules: Dict[str, str] = {}
        self.error_patterns: List[dict] = []
        self.gates: List[Tuple[str, callable]] = []
        self._load_rules()
        self._load_error_patterns()
    
    # ── 1. AGENTS.md 规则加载 ──
    def _load_rules(self):
        """加载AGENTS.md中的项目规则"""
        agents_md = self.root / "AGENTS.md"
        if not agents_md.exists():
            return
        
        content = agents_md.read_text()
        # 解析规则章节
        current_section = "general"
        for line in content.split('\n'):
            if line.startswith('## '):
                current_section = line[3:].strip()
            elif line.startswith('- ') or line.startswith('1. ') or line.startswith('2. '):
                rule = line.lstrip('- 0123456789. ')
                if rule:
                    self.rules[f"{current_section}/{rule[:50]}"] = rule
    
    # ── 2. 错误模式学习 ──
    def _load_error_patterns(self):
        """加载已知错误模式"""
        patterns_file = self.root / ".meshctx" / "error_patterns.json"
        if patterns_file.exists():
            self.error_patterns = json.loads(patterns_file.read_text())["patterns"]
    
    def learn_error(self, category: str, symptom: str, root_cause: str, fix: str):
        """学习新的错误模式"""
        pattern = {
            "category": category,
            "symptom": symptom,
            "root_cause": root_cause,
            "fix": fix,
            "learned_at": datetime.now().isoformat(),
            "occurrences": 1
        }
        # 检查是否已存在
        for p in self.error_patterns:
            if p["symptom"] == symptom:
                p["occurrences"] += 1
                p["learned_at"] = datetime.now().isoformat()
                self._save_patterns()
                return
        
        self.error_patterns.append(pattern)
        self._save_patterns()
    
    def _save_patterns(self):
        patterns_dir = self.root / ".meshctx"
        patterns_dir.mkdir(exist_ok=True)
        (patterns_dir / "error_patterns.json").write_text(
            json.dumps({"patterns": self.error_patterns, "updated": datetime.now().isoformat()}, indent=2)
        )
    
    def check_for_known_errors(self, code: str) -> List[str]:
        """检查代码是否包含已知错误模式"""
        warnings = []
        checks = {
            "console=False": "console=False会导致Windows GUI应用丢失stdin→崩溃",
            "encoding='utf-8'": None,  # 正确模式，不警告
            "sys.stdout.reconfigure": None,  # 正确模式
        }
        for pattern, warning in checks.items():
            if warning and pattern in code:
                warnings.append(f"⚠️ 已知错误模式: {warning}")
        return warnings
    
    # ── 3. 预提交门禁 ──
    def pre_commit_check(self) -> Tuple[bool, List[str]]:
        """提交前检查 — 所有门禁必须通过"""
        failures = []
        
        # 门禁1: 测试
        result = subprocess.run(
            ["python", "-m", "pytest", "tests/test_nsis_validation.py", 
             "tests/test_project_integrity.py", "tests/test_real_behavior.py", 
             "-q", "--tb=line"],
            cwd=self.root, capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            failures.append(f"测试失败: {result.stdout[-200:]}")
        
        # 门禁2: 版本号一致性
        result = subprocess.run(
            ["python3", "tools/sync_version.py"],
            cwd=self.root, capture_output=True, text=True, timeout=10
        )
        if "OK" not in result.stdout:
            failures.append("版本号不一致")
        
        # 门禁3: 禁止模式
        for f in self.root.rglob("*.py"):
            if '__pycache__' in str(f) or '.git' in str(f):
                continue
            try:
                code = f.read_text()
                warnings = self.check_for_known_errors(code)
                for w in warnings:
                    failures.append(f"{f.name}: {w}")
            except:
                pass
        
        return len(failures) == 0, failures
    
    # ── 4. 发布闸门 ──
    def release_gate(self, version: str) -> Tuple[bool, List[str]]:
        """发布前最终闸门 — 全部通过才能打tag"""
        gates = [
            ("全量测试", self._run_full_tests),
            ("版本同步", lambda: self._check_version_sync(version)),
            ("NSIS验证", self._check_nsis),
            ("exe版本信息", self._check_exe_version),
        ]
        
        failures = []
        for name, check in gates:
            try:
                ok, msg = check()
                if not ok:
                    failures.append(f"{name}: {msg}")
            except Exception as e:
                failures.append(f"{name}: {str(e)}")
        
        return len(failures) == 0, failures
    
    def _run_full_tests(self):
        result = subprocess.run(
            ["python", "-m", "pytest", "tests/", "-q", "--tb=line"],
            cwd=self.root, capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            return False, result.stdout[-300:]
        # 检查是否有failed
        if "failed" in result.stdout:
            return False, result.stdout
        return True, "OK"
    
    def _check_version_sync(self, version):
        result = subprocess.run(
            ["python3", "tools/sync_version.py", version],
            cwd=self.root, capture_output=True, text=True, timeout=10
        )
        return result.returncode == 0, result.stdout
    
    def _check_nsis(self):
        nsi = self.root / "meshctx_setup.nsi"
        if not nsi.exists():
            return False, "NSIS文件不存在"
        content = nsi.read_text()
        checks = [
            ("7语言", len(re.findall(r'MUI_LANGUAGE "', content)) >= 7),
            ("UTF-8 BOM", nsi.read_bytes()[:3] == b'\xef\xbb\xbf'),
            ("VIProductVersion", "VIProductVersion" in content),
            ("LangDLL插件", "LangDLL.dll" in content or "LangDLL" in content),
        ]
        failures = [name for name, ok in checks if not ok]
        return len(failures) == 0, f"缺失: {', '.join(failures)}" if failures else "OK"
    
    def _check_exe_version(self):
        exe = self.root / "dist" / "meshctx-desktop.exe"
        if not exe.exists():
            return True, "SKIP(本地无exe)"  # CI会构建
        data = exe.read_bytes()
        has_ver = b'F\x00i\x00l\x00e\x00V' in data
        return has_ver, "版本信息已嵌入" if has_ver else "版本信息缺失!"
    
    # ── 5. 状态报告 ──
    def status(self) -> dict:
        return {
            "rules_loaded": len(self.rules),
            "error_patterns": len(self.error_patterns),
            "known_bugs": [p["symptom"] for p in self.error_patterns],
        }


# 单例
_governance: Optional[AgentGovernance] = None

def get_governance() -> AgentGovernance:
    global _governance
    if _governance is None:
        _governance = AgentGovernance()
    return _governance
