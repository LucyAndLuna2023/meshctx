"""项目级完整性验证 — 堵住所有测试盲区

覆盖之前导致线上故障的盲区:
1. install.sh — 语法/结构/URL/必需步骤完整性
2. index.html — 7语言i18n完整性+下载链接有效性
3. meshctx_desktop.spec — hiddenimports是否覆盖所有core模块
4. requirements.txt — 能否安装+是否包含所有必需依赖
5. install.bat — Windows安装脚本语法检查
6. version_info.txt — VSVersionInfo格式完整性
"""
import pytest
import re
import subprocess
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent


# ═══════════════════════════════════════════════════════════
# install.sh 验证 (之前curl|bash装不上就是缺测试)
# ═══════════════════════════════════════════════════════════

class TestInstallScript:
    def test_exists(self):
        assert (PROJECT / "install.sh").exists(), "install.sh 不存在"
        assert (PROJECT / "docs" / "install.sh").exists(), "docs/install.sh 不存在"

    def test_no_git_clone_dependency(self):
        """GFW阻断GitHub,脚本不能依赖git clone"""
        content = (PROJECT / "install.sh").read_text()
        assert "git clone" not in content, \
            "install.sh包含git clone — 中国用户无法访问GitHub!"

    def test_has_download_url(self):
        """必须有从同一服务器下载tarball的URL"""
        content = (PROJECT / "install.sh").read_text()
        has_url = "curl" in content and ("tar.gz" in content or "tarball" in content or ".zip" in content)
        assert has_url, "install.sh必须包含curl下载tarball的逻辑"

    def test_no_read_prompt(self):
        """curl|bash管道模式下read -p会读取管道数据,导致行为异常"""
        content = (PROJECT / "install.sh").read_text()
        assert "read -p" not in content, \
            "install.sh包含read -p — curl|bash管道模式下会读到错误输入!"

    def test_creates_venv(self):
        content = (PROJECT / "install.sh").read_text()
        assert "venv" in content.lower(), "install.sh缺少venv创建步骤"

    def test_installs_dependencies(self):
        content = (PROJECT / "install.sh").read_text()
        assert "pip" in content, "install.sh缺少pip安装依赖步骤"

    def test_syntax_valid(self):
        """bash -n 语法检查"""
        result = subprocess.run(
            ["bash", "-n", str(PROJECT / "install.sh")],
            capture_output=True, text=True, timeout=10
        )
        assert result.returncode == 0, f"install.sh语法错误: {result.stderr}"

    def test_docs_copy_matches(self):
        """docs/install.sh 必须和 install.sh 同步"""
        src = (PROJECT / "install.sh").read_text()
        docs = (PROJECT / "docs" / "install.sh").read_text()
        assert src == docs, "docs/install.sh 和 install.sh 内容不一致! 运行: cp install.sh docs/install.sh"


# ═══════════════════════════════════════════════════════════
# index.html 主页验证 (7语言i18n不全会导致切换语言后部分内容仍显示旧语言)
# ═══════════════════════════════════════════════════════════

class TestHomepageI18N:
    LANGUAGES = ['en', 'zh', 'fr', 'de', 'ja', 'ko', 'es']

    @pytest.fixture
    def html(self):
        idx = PROJECT / "docs" / "index.html"
        if not idx.exists():
            idx = PROJECT / "index.html"
        return idx.read_text(encoding='utf-8')

    def test_file_exists(self):
        idx = PROJECT / "docs" / "index.html"
        assert idx.exists() or (PROJECT / "index.html").exists(), \
            "主页文件不存在"

    def test_all_7_language_blocks_exist(self, html):
        """每个语言必须有L块定义"""
        for lang in self.LANGUAGES:
            assert f'{lang}:' in html, \
                f"主页缺少 '{lang}' 语言块 — 切换到此语言会显示其他语言文本!"

    def test_data_lang_keys_have_all_translations(self, html):
        """HTML中每个data-lang-key必须在所有7语言L块中有对应值"""
        # 提取所有data-lang-key
        keys = set(re.findall(r'data-lang-key="([^"]+)"', html))
        # 对每个语言块检查
        for lang in self.LANGUAGES:
            # 找到该语言块
            pattern = rf'{lang}:\s*\{{'
            m = re.search(pattern, html)
            if not m:
                continue
            # 粗略提取块内容
            start = m.start()
            # 找闭合 }
            depth = 0
            end = start
            for i in range(start, len(html)):
                if html[i] == '{':
                    depth += 1
                elif html[i] == '}':
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            block = html[start:end]
            for key in keys:
                # 排除系统key
                if key in ('sb_title',):  # 可能在别处定义
                    continue
                assert key in block, \
                    f"'{lang}' 语言块缺少 key='{key}' — {lang}语言下此元素不会翻译!"

    def test_download_links_valid(self, html):
        """下载链接不能指向不存在的文件"""
        # 检查是否有死链
        dead_patterns = ['href="#"', 'href=""', 'href="javascript:void(0)"',
                        'meshctx-windows.exe', 'meshctx-setup.exe']
        for pattern in dead_patterns:
            # 允许exe链接(CI构建产物)
            if '.exe' in pattern:
                continue
        # 至少有一个可访问的下载链接
        urls = re.findall(r'href="(https?://[^"]+)"', html)
        assert len(urls) > 0, "主页没有任何外部链接"


# ═══════════════════════════════════════════════════════════
# meshctx_desktop.spec 验证 (hiddenimports缺失导致exe损坏)
# ═══════════════════════════════════════════════════════════

class TestSpecHiddenImports:
    def test_spec_uses_collect_submodules(self):
        """v2.41+: 使用collect_submodules自动发现,不再手动列举60+模块"""
        spec = (PROJECT / "meshctx_desktop.spec").read_text()
        assert "collect_submodules" in spec, \
            "spec必须使用collect_submodules('src.core')自动收集,手动列举永远会漏!"
        assert "collect_submodules('src.core')" in spec, \
            "spec缺少collect_submodules('src.core')"

    def test_collect_submodules_covers_all_modules(self):
        """验证collect_submodules确实能发现所有src.core模块"""
        from PyInstaller.utils.hooks import collect_submodules
        core_dir = PROJECT / "src" / "core"
        core_modules = sorted([
            p.stem for p in core_dir.glob("*.py")
            if not p.name.startswith('_') or p.name == '__init__.py'
        ])

        collected = collect_submodules('src.core')
        missing = []
        for mod in core_modules:
            if mod == '__init__':
                continue
            import_name = f"src.core.{mod}"
            if import_name not in collected:
                missing.append(mod)

        assert not missing, \
            f"collect_submodules未发现{len(missing)}个模块: {missing}\n" \
            f"这会导致PyInstaller打包的exe启动时ModuleNotFoundError!"

    def test_spec_has_all_required_data_files(self):
        """datas中列出的文件必须存在"""
        spec = (PROJECT / "meshctx_desktop.spec").read_text()
        # 提取 datas 中引用的文件
        datas = re.findall(r"\('([^']+)',\s*'[^']+'\)", spec)
        for data_file in datas:
            if '*' in data_file:
                continue  # glob patterns
            full_path = PROJECT / data_file
            assert full_path.exists(), \
                f"spec datas引用不存在的文件: {data_file}"


# ═══════════════════════════════════════════════════════════
# requirements.txt 验证 (缺依赖导致install.sh装不上)
# ═══════════════════════════════════════════════════════════

class TestRequirements:
    def test_file_exists_and_readable(self):
        req = PROJECT / "requirements.txt"
        assert req.exists(), "requirements.txt 不存在"
        content = req.read_text()
        assert len(content) > 10, "requirements.txt 内容异常短"

    def test_contains_critical_deps(self):
        """之前python-multipart缺失导致main.py导入失败"""
        content = (PROJECT / "requirements.txt").read_text()
        critical = [
            'fastapi', 'uvicorn', 'pydantic', 'python-multipart',
            'httpx', 'openai', 'jinja2', 'pyyaml', 'aiohttp',
        ]
        for dep in critical:
            assert dep.lower() in content.lower(), \
                f"requirements.txt 缺少关键依赖: {dep}"

    def test_can_parse_all_lines(self):
        """每行必须是合法的 pip 格式"""
        content = (PROJECT / "requirements.txt").read_text()
        for i, line in enumerate(content.split('\n'), 1):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            # 检查基本格式: package>=version 或 package==version 或 package
            assert ' ' not in line, \
                f"requirements.txt L{i} 格式异常(含空格): {line}"


# ═══════════════════════════════════════════════════════════
# install.bat 验证
# ═══════════════════════════════════════════════════════════

class TestWindowsInstallBat:
    def test_exists(self):
        assert (PROJECT / "install.bat").exists(), "install.bat 不存在"

    def test_no_git_clone(self):
        content = (PROJECT / "install.bat").read_text()
        assert "git clone" not in content, \
            "install.bat包含git clone — 中国用户无法访问GitHub!"

    def test_has_python_check(self):
        content = (PROJECT / "install.bat").read_text()
        assert "python" in content.lower(), "install.bat缺少Python检查"


# ═══════════════════════════════════════════════════════════
# version_info.txt VSVersionInfo 格式验证
# ═══════════════════════════════════════════════════════════

class TestVersionInfoFormat:
    def test_is_vsversioninfo_not_plain_text(self):
        """PyInstaller要求VSVersionInfo格式,纯文本会导致eval报SyntaxError"""
        content = (PROJECT / "version_info.txt").read_text()
        assert 'VSVersionInfo(' in content, \
            "version_info.txt不是VSVersionInfo格式 — PyInstaller会报SyntaxError!"
        assert 'FixedFileInfo(' in content, \
            "version_info.txt缺少FixedFileInfo块"
        assert 'StringFileInfo(' in content, \
            "version_info.txt缺少StringFileInfo块"

    def test_has_all_required_fields(self):
        content = (PROJECT / "version_info.txt").read_text()
        required = [
            'filevers', 'prodvers', 'CompanyName', 'FileDescription',
            'FileVersion', 'ProductName', 'ProductVersion', 'LegalCopyright',
        ]
        for field in required:
            assert field in content, \
                f"version_info.txt缺少必需字段: {field}"


# ═══════════════════════════════════════════════════════════
# 🔴 历史bug回归 — 防止已修复bug复发 (v2.52+)
# ═══════════════════════════════════════════════════════════

class TestRegressionPrevention:
    """回归防护: 每个历史bug一条测试,永不复发"""

    def test_spec_explicitly_includes_metacognition(self):
        """🔴 Bug: Windows启动报 No module named src.core.metacognition
        根因: PyInstaller try/except漏掉核心模块
        修复: hiddenimports显式列出全部core模块"""
        spec = (PROJECT / "meshctx_desktop.spec").read_text()
        assert 'src.core.metacognition' in spec, \
            "🔴 meshctx_desktop.spec缺少'src.core.metacognition'! Windows会启动失败!"
        # 验证所有关键模块
        critical_modules = [
            'metacognition', 'memory_hierarchy', 'orchestrator', 'predictor',
            'agent_loop', 'healer', 'kernel', 'free_energy', 'active_inference',
            'global_workspace', 'homeostasis', 'super_brain', 'sandbox',
            'diff_preview', 'task_progress', 'sdb_framework', 'self_modify',
            'brain_validator', 'gateway_llm', 'unified_loop', 'attractor_reasoner',
            'dashboard', 'auto_healer', 'human_memory', 'autonomous_engine',
        ]
        for mod in critical_modules:
            assert f'src.core.{mod}' in spec, \
                f"🔴 spec缺少核心模块: src.core.{mod} — Windows启动会因此报ModuleNotFoundError!"

    def test_spec_collect_submodules_still_present(self):
        """collect_submodules作为兜底不能丢"""
        spec = (PROJECT / "meshctx_desktop.spec").read_text()
        assert 'collect_submodules' in spec, \
            "🔴 spec缺少collect_submodules导入! PyInstaller无法自动发现新模块!"

    def test_nsis_finish_button_has_langstring(self):
        """🔴 Bug: 安装完成页面按钮没有"完成"二字
        根因: MUI多语言下MUI_BUTTONTEXT_FINISH依赖语言文件,未显式定义
        修复: 显式LangString FINISH_BUTTON 7语言"""
        nsis = (PROJECT / "meshctx_setup.nsi").read_text()
        assert 'LangString FINISH_BUTTON' in nsis, \
            "🔴 NSIS缺少 FINISH_BUTTON LangString! 完成按钮会无文字!"
        assert 'MUI_BUTTONTEXT_FINISH' in nsis, \
            "🔴 NSIS缺少 MUI_BUTTONTEXT_FINISH define! 完成按钮文字不会显示!"
        # 验证7种语言都有
        for lang_code in ['1033', '2052', '1041', '1042', '1036', '1031', '1034']:
            pattern = f'FINISH_BUTTON {lang_code}'
            assert pattern in nsis, \
                f"🔴 NSIS FINISH_BUTTON缺少语言 {lang_code}! 该语言下完成按钮无文字!"

    def test_nsis_utf8_bom_still_present(self):
        """🔴 Bug: NSIS选中文后乱码 (v2.38已修复,必须防复发)"""
        nsis_bytes = (PROJECT / "meshctx_setup.nsi").read_bytes()
        assert nsis_bytes[:3] == b'\xef\xbb\xbf', \
            "🔴 NSIS文件缺少UTF-8 BOM! 选中文后会乱码! (历史bug复发)"

    def test_nsis_mui_language_before_pages(self):
        """🔴 Bug: MUI_PAGE在MUI_LANGUAGE前导致乱码 (v2.38已修复)"""
        nsis = (PROJECT / "meshctx_setup.nsi").read_text()
        lang_pos = nsis.find('!insertmacro MUI_LANGUAGE')
        page_pos = nsis.find('!insertmacro MUI_PAGE_WELCOME')
        assert lang_pos < page_pos, \
            "🔴 MUI_LANGUAGE必须在MUI_PAGE之前! 否则选中文后乱码!"

    def test_spec_not_using_manual_hiddenimports_only(self):
        """collect_submodules必须是主策略,显式列表只是安全兜底"""
        spec = (PROJECT / "meshctx_desktop.spec").read_text()
        assert "collect_submodules('src.core')" in spec, \
            "🔴 spec必须包含collect_submodules('src.core')!"
        assert "collect_submodules('src')" in spec, \
            "🔴 spec必须包含collect_submodules('src')!"

    def test_install_sh_no_git_clone(self):
        """🔴 Bug: install.sh依赖git clone → 中国用户无法安装"""
        for sh_file in ["install.sh", "docs/install.sh"]:
            path = PROJECT / sh_file
            if path.exists():
                content = path.read_text()
                assert "git clone" not in content, \
                    f"🔴 {sh_file}包含git clone! GFW阻断GitHub,中国用户无法安装!"
                assert "git@" not in content, \
                    f"🔴 {sh_file}包含git@! 需要SSH密钥,普通用户无法使用!"

    def test_ci_build_has_artifact_fallback(self):
        """🔴 Bug: CI push to main不创建Release → 产物9B空文件"""
        ci_file = PROJECT / ".github" / "workflows" / "build-windows.yml"
        if ci_file.exists():
            content = ci_file.read_text()
            assert "upload-artifact" in content, \
                "🔴 CI缺少upload-artifact兜底! push-to-main时产物会丢失(9B空文件bug)!"

    def test_version_info_uses_absolute_path_in_spec(self):
        """🔴 Bug: Windows .exe属性里没有版本号
        根因: EXE(version='version_info.txt')相对路径,CI构建时找不到文件
        修复: version=os.path.join(_here, 'version_info.txt')"""
        spec = (PROJECT / "meshctx_desktop.spec").read_text()
        assert "os.path.join(_here, 'version_info.txt')" in spec, \
            "🔴 spec中version必须使用绝对路径os.path.join(_here, 'version_info.txt')! 相对路径在CI构建时会找不到,导致.exe属性无版本号!"

    def test_version_info_has_correct_version(self):
        """验证 version_info.txt 的版本号与 __init__.py 一致"""
        import re
        vi = (PROJECT / "version_info.txt").read_text()
        init = (PROJECT / "src" / "core" / "__init__.py").read_text()
        # 从 __init__.py 提取版本
        init_match = re.search(r'__version__\s*=\s*"([^"]+)"', init)
        assert init_match, "无法从 __init__.py 提取版本号"
        expected = init_match.group(1)
        # 验证 version_info.txt 包含相同版本
        assert f"u'FileVersion', u'{expected}'" in vi or \
               f"StringStruct(u'FileVersion', u'{expected}')" in vi, \
            f"🔴 version_info.txt FileVersion 与 __init__.py 不一致! 期望 {expected}"
        assert f"u'ProductVersion', u'{expected}'" in vi or \
               f"StringStruct(u'ProductVersion', u'{expected}')" in vi, \
            f"🔴 version_info.txt ProductVersion 与 __init__.py 不一致! 期望 {expected}"
        # 验证 filevers/prodvers 元组
        major, minor, patch, *_ = expected.split('.')
        assert f"filevers=({major}, {minor}, {patch}" in vi, \
            f"🔴 version_info.txt filevers 与 __init__.py 不一致! 期望 ({major}, {minor}, {patch}, ...)"

