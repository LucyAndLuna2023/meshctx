"""
MeshCtx Pre-Action Checker — 行动前自动校验
==========================================
在文件修改/部署前自动检查已知原则,阻止重复错误。
集成到OODA循环的Orient→Decide阶段。
"""

import subprocess, ast, re
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from .principle_extractor import get_extractor, PrincipleExtractor

class PreActionChecker:
    """行动前检查器"""
    
    def __init__(self):
        self.extractor = get_extractor()
        self.last_check_results: List[Dict] = []
    
    def check_before_modify(self, file_path: str, content: str = None) -> Tuple[bool, List[str]]:
        """
        文件修改前检查
        返回: (是否通过, 警告/错误列表)
        """
        warnings = []
        errors = []
        ext = Path(file_path).suffix.lower()
        
        # 1. 查询相关原则
        principles = self.extractor.query(file_path=file_path)
        
        # 2. 自动语法检查
        syntax_ok, syntax_msg = self._auto_syntax_check(file_path, content, ext)
        if not syntax_ok:
            errors.append(f"❌ 语法错误: {syntax_msg}")
        
        # 3. 按原则逐项检查
        for p in principles:
            result = self._check_principle(p, file_path, content, ext)
            if result:
                if p.get("severity") == "critical":
                    errors.append(f"🔴 [{p['id']}] {result}")
                else:
                    warnings.append(f"🟡 [{p['id']}] {result}")
        
        self.last_check_results = [
            {"type": "error", "msg": e} for e in errors
        ] + [{"type": "warning", "msg": w} for w in warnings]
        
        # critical错误阻止操作
        return len(errors) == 0, warnings + errors
    
    def check_before_deploy(self, changed_files: List[str]) -> Tuple[bool, List[str]]:
        """部署前检查"""
        issues = []
        
        # 检查是否包含所有修改的文件
        if "src/web_ui.py" in changed_files and "src/main.py" not in changed_files:
            issues.append("⚠️ web_ui.py修改了但main.py未同步,确认否?")
        
        # 检查是否包含.pyc缓存
        pyc_files = [f for f in changed_files if f.endswith('.pyc')]
        if pyc_files:
            issues.append(f"⚠️ 包含{len(pyc_files)}个.pyc文件,部署前应清除缓存")
        
        return len([i for i in issues if i.startswith('❌')]) == 0, issues
    
    def _auto_syntax_check(self, file_path: str, content: str, ext: str) -> Tuple[bool, str]:
        """自动语法检查"""
        if content is None:
            try:
                with open(file_path) as f:
                    content = f.read()
            except:
                return True, ""
        
        try:
            if ext == '.py':
                ast.parse(content)
                return True, ""
            elif ext == '.html':
                # 提取JS并验证
                scripts = re.findall(r'<script>(.*?)</script>', content, re.DOTALL)
                if scripts:
                    with open('/tmp/_pre_check.js', 'w') as f:
                        f.write(scripts[-1])
                    r = subprocess.run(['node', '--check', '/tmp/_pre_check.js'],
                                     capture_output=True, text=True, timeout=10)
                    if r.returncode != 0:
                        # 提取第一个错误行
                        err_line = r.stderr.strip().split('\n')[0]
                        return False, f"JS语法错误: {err_line[:200]}"
            elif ext == '.nsi':
                # NSIS基本检查: $\n vs $\\n
                if b'$\\\\n' in content.encode() if isinstance(content, str) else b'$\\\\n' in content:
                    return False, "NSIS包含$\\\\n(双反斜杠),应改为$\\n"
            return True, ""
        except SyntaxError as e:
            return False, f"Python语法错误 line {e.lineno}: {e.msg}"
        except Exception as e:
            return False, str(e)[:200]
    
    def _check_principle(self, p: Dict, file_path: str, content: str, ext: str) -> Optional[str]:
        """检查单条原则"""
        pid = p.get("id", "")
        
        # Python yaml导入检查
        if pid == "py-yaml-import" and ext == '.py':
            if content is None:
                try:
                    with open(file_path) as f:
                        content = f.read()
                except:
                    return None
            
            # 查找使用yaml.但没有import yaml的函数
            lines = content.split('\n')
            yaml_lines = [i for i, l in enumerate(lines) if 'yaml.' in l and not l.strip().startswith('#')]
            for yl in yaml_lines:
                # 向上搜索函数定义和import yaml
                has_import = False
                for i in range(yl-1, max(0, yl-80), -1):
                    if 'import yaml' in lines[i]:
                        has_import = True
                        break
                    if lines[i].strip().startswith('def ') or lines[i].strip().startswith('async def '):
                        break
                if not has_import:
                    # 再检查函数外的import
                    func_start = 0
                    for i in range(yl-1, 0, -1):
                        if lines[i].strip().startswith('def ') or lines[i].strip().startswith('async def '):
                            func_start = i
                            break
                    # 检查函数外(top-level)是否有import yaml
                    for i in range(func_start-1, max(0, func_start-200), -1):
                        if 'import yaml' in lines[i]:
                            has_import = True
                            break
                    if not has_import:
                        return f"Line {yl+1}: 使用yaml但函数内未import yaml"
        
        # HTML JS逗号检查
        if pid == "html-js-comma" and ext == '.html':
            if content is None:
                try:
                    with open(file_path) as f:
                        content = f.read()
                except:
                    return None
            
            # 检查L对象中的逗号缺失
            scripts = re.findall(r'<script>(.*?)</script>', content, re.DOTALL)
            if scripts:
                js = scripts[-1]
                L_match = re.search(r'const L\s*=\s*\{', js)
                if L_match:
                    L_body = js[L_match.start():]
                    # 查找 pattern: key:"val"\n        next_key:"val" (缺少逗号)
                    missing_commas = re.findall(
                        r'(\w+):"([^"]*)"\n\s+(\w+):',
                        L_body
                    )
                    if missing_commas:
                        examples = [f'{m[0]}:... → {m[2]}:...' for m in missing_commas[:3]]
                        return f"L对象可能缺逗号: {', '.join(examples)}"
        
        # NSIS换行检查
        if pid == "nsi-backslash-n" and ext == '.nsi':
            try:
                with open(file_path, 'rb') as f:
                    data = f.read()
                if b'$\\\\n' in data:
                    count = data.count(b'$\\\\n')
                    return f"包含{count}处$\\\\n(应改为$\\n)"
            except:
                pass
        
        # f-string反斜杠检查
        if pid == "py-fstring-backslash" and ext == '.py':
            if content is None:
                try:
                    with open(file_path) as f:
                        content = f.read()
                except:
                    return None
            # 查找 f"...\\... 模式
            matches = re.findall(r'f"[^"]*\\\\[^"]*"', content)
            if matches:
                return f"可能包含f-string反斜杠({len(matches)}处),检查Python 3.10兼容"
        
        # 模型吞异常检查
        if pid == "model-chat-no-swallow" and ext == '.py':
            if content is None:
                try:
                    with open(file_path) as f:
                        content = f.read()
                except:
                    return None
            if 'except Exception as e:' in content and 'return {\"content\": f\"[错误' in content:
                return "ModelClient.chat()在吞异常返回假成功,应抛出真实异常"
        
        return None


# ── 单例 ──
_checker: Optional[PreActionChecker] = None

def get_checker() -> PreActionChecker:
    global _checker
    if _checker is None:
        _checker = PreActionChecker()
    return _checker


def quick_check(file_path: str) -> Tuple[bool, List[str]]:
    """快速检查(便捷函数)"""
    return get_checker().check_before_modify(file_path)
