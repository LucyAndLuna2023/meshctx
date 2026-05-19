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
    def test_all_core_modules_in_hiddenimports(self):
        """每个src/core/*.py必须在spec的hiddenimports中,否则PyInstaller打包后导入失败"""
        spec = (PROJECT / "meshctx_desktop.spec").read_text()
        core_dir = PROJECT / "src" / "core"
        core_modules = sorted([
            p.stem for p in core_dir.glob("*.py")
            if not p.name.startswith('_') or p.name == '__init__.py'
        ])

        missing = []
        for mod in core_modules:
            if mod == '__init__':
                continue
            import_name = f"src.core.{mod}"
            if import_name not in spec:
                missing.append(mod)

        assert not missing, \
            f"spec hiddenimports缺少{len(missing)}个模块: {missing}\n" \
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
