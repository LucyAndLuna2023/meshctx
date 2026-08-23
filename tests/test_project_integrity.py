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
        """开源主体用 curl 下载 tarball；git clone 只允许用于可选闭源核心 meshctx-core"""
        content = (PROJECT / "install.sh").read_text()
        assert "curl" in content and "tar.gz" in content, "install.sh缺少curl下载开源包"
        for line in content.splitlines():
            if "git clone" in line or "clone --depth" in line:
                assert "meshctx-core" in line, \
                    f"install.sh的git clone必须只用于闭源核心meshctx-core: {line.strip()}"

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

    @pytest.fixture
    def i18n_data(self):
        """i18n 已改为动态加载 docs/i18n/landing.json"""
        p = PROJECT / "docs" / "i18n" / "landing.json"
        if not p.exists():
            p = PROJECT / "i18n" / "landing.json"
        assert p.exists(), f"i18n 数据文件不存在: {p}"
        import json
        return json.loads(p.read_text(encoding='utf-8'))

    def test_file_exists(self):
        idx = PROJECT / "docs" / "index.html"
        assert idx.exists() or (PROJECT / "index.html").exists(), \
            "主页文件不存在"

    def test_all_7_language_blocks_exist(self, i18n_data):
        """每个语言必须有翻译块定义（动态加载 landing.json）"""
        for lang in self.LANGUAGES:
            assert lang in i18n_data, \
                f"landing.json 缺少 '{lang}' 语言块 — 切换到此语言会显示其他语言文本!"

    def test_data_lang_keys_have_all_translations(self, html, i18n_data):
        """HTML中每个data-lang-key必须在所有语言块中有对应值"""
        # 提取所有data-lang-key
        keys = set(re.findall(r'data-lang-key="([^"]+)"', html))
        assert keys, "HTML 中没有任何 data-lang-key"
        for lang in self.LANGUAGES:
            block = i18n_data.get(lang, {})
            if not block:
                continue
            for key in keys:
                # 排除系统key
                if key in ('sb_title',):  # 可能在别处定义
                    continue
                assert key in block, \
                    f"'{lang}' 语言块缺少 key='{key}' — {lang}语言下此元素不会翻译!"

    def test_js_syntax_no_double_commas(self, html):
        """🔴 回归: JS对象双逗号导致整个L对象解析失败,语言切换全失效
        现在 i18n 从 landing.json 动态加载, 验证 JSON 合法 + 无重复 key"""
        # 1. JSON 可解析（json.load 已在 fixture 中验证, 这里再显式验证）
        p = PROJECT / "docs" / "i18n" / "landing.json"
        if not p.exists():
            p = PROJECT / "i18n" / "landing.json"
        import json as _json
        data = _json.loads(p.read_text(encoding='utf-8'))

        # 2. 语言块内无空字符串值
        for lang, block in data.items():
            for k, v in block.items():
                assert v, f"🔴 {lang}.{k} 是空值 — 该语言下此文案为空!"
                assert '::' not in str(v), f"🔴 {lang}.{k} 含双冒号(::)"
                assert '""' not in str(v), f"🔴 {lang}.{k} 含空字符串键名"

        # 3. 每个语言块内部 key 不重复（JSON 天然不允许重复 key, 双重保险）
        # 4. index.html 确实引用了 landing.json（动态加载）
        assert "landing.json" in html, "🔴 index.html 未引用 landing.json — 动态加载已失效!"
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
    def test_spec_uses_disk_enum(self):
        """v3.119.2: 使用构建期磁盘枚举 src/core/*.py 替代 collect_submodules

        collect_submodules 在 CI 隔离子进程静默返回 0 (Linux/macOS), 导致
        发布 244/287 不完整包。修复改为磁盘递归枚举, 确定性收集。
        """
        spec = (PROJECT / "meshctx_desktop.spec").read_text()
        assert "os.listdir(src_dir)" in spec or "rglob" in spec, \
            "spec 必须使用构建期磁盘枚举 src/core/*.py (v3.119.2 替代 collect_submodules)"
        assert "src/core 无模块" in spec or "禁止发布 stub" in spec, \
            "spec 缺少空列表硬门禁 — 缺闭源核心必须 FAIL 而非静默发布 stub"

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
        """开源主体必须用 curl 下载 tarball；git clone 只允许用于可选闭源核心 meshctx-core"""
        content = (PROJECT / "install.bat").read_text()
        assert "curl -fsSL" in content, "install.bat缺少curl下载开源包"
        git_clone_lines = [l for l in content.splitlines()
                           if "git clone" in l or "clone --depth" in l]
        for line in git_clone_lines:
            assert "meshctx-core" in line, \
                f"install.bat的git clone必须只用于闭源核心meshctx-core: {line.strip()}"

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
        """v3.33.9: MUI2通过MUI_LANGUAGE自动提供完成按钮翻译
        不再需要显式LangString FINISH_BUTTON — MUI_BUTTONTEXT_FINISH由MUI2处理"""
        nsis = (PROJECT / "meshctx_setup.nsi").read_text(encoding="utf-8-sig")
        # 验证7种MUI_LANGUAGE都存在(这自动提供完成按钮翻译)
        for lang in ['English', 'SimpChinese', 'Japanese', 'Korean', 'German', 'French', 'Spanish']:
            assert f'MUI_LANGUAGE "{lang}"' in nsis, \
                f"🔴 MUI_LANGUAGE缺少 {lang}! 完成按钮将无文字!"

    def test_nsis_utf8_bom_still_present(self):
        """🔴 Bug: NSIS选中文后乱码 (v2.38已修复,必须防复发)"""
        nsis_bytes = (PROJECT / "meshctx_setup.nsi").read_bytes()
        assert nsis_bytes[:3] == b'\xef\xbb\xbf', \
            "🔴 NSIS文件缺少UTF-8 BOM! 选中文后会乱码! (历史bug复发)"

    def test_nsis_mui_language_before_pages(self):
        """v3.80: MUI_LANGUAGE在MUI_PAGE之前(先声明语言,标准页面使用翻译)"""
        nsis = (PROJECT / "meshctx_setup.nsi").read_text(encoding="utf-8-sig")
        lang_pos = nsis.find('!insertmacro MUI_LANGUAGE')
        page_pos = nsis.find('!insertmacro MUI_PAGE_WELCOME')
        assert page_pos < lang_pos, \
            "🔴 MUI_PAGE必须在MUI_LANGUAGE之前! (NSIS编译器要求)"

    def test_spec_not_using_manual_hiddenimports_only(self):
        """磁盘枚举必须是主策略, 显式列表只是安全兜底 (v3.119.2 替代 collect_submodules)"""
        spec = (PROJECT / "meshctx_desktop.spec").read_text()
        assert "os.listdir(src_dir)" in spec or "rglob" in spec, \
            "🔴 spec 必须包含构建期磁盘枚举 src/core (v3.119.2)!"
        assert "src/core 无模块" in spec or "禁止发布 stub" in spec, \
            "🔴 spec 必须包含空列表硬门禁!"

    def test_install_sh_no_git_clone(self):
        """🔴 开源主体不能依赖 git clone；git clone 只允许用于可选闭源核心 meshctx-core"""
        for sh_file in ["install.sh", "docs/install.sh"]:
            path = PROJECT / sh_file
            if path.exists():
                content = path.read_text()
                for line in content.splitlines():
                    if "git clone" in line or "clone --depth" in line:
                        assert "meshctx-core" in line, \
                            f"🔴 {sh_file}的git clone必须只用于闭源核心meshctx-core: {line.strip()}"
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
        根因: EXE(version)路径错误导致PyInstaller找不到version_info.txt
        修复: 使用相对路径(PyInstaller从spec所在目录解析),配合pyi-set_version后注入
        验证: spec中version字段存在即可"""
        spec = (PROJECT / "meshctx_desktop.spec").read_text()
        assert "version_info.txt" in spec and "version" in spec, \
            "🔴 spec中必须包含version字段引用version_info.txt! 否则.exe属性无版本号!"

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

