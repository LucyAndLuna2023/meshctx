"""NSIS安装脚本结构验证 — 防止乱码回归

测试覆盖:
1. UTF-8 BOM 检测 — 缺BOM导致CJK乱码
2. MUI_LANGUAGE/MUI_PAGE 顺序检测 — 语言必须在页面之前
3. LangString 7语言完整性 — 每组6个LangString各需7语言
4. 版本一致性 — .nsi/.spec/version_info.txt/__init__.py 版本号同步
5. UNPAGE顺序 — CONFIRM必须在INSTFILES之前
"""
import pytest
import re
from pathlib import Path

PROJECT = Path(__file__).resolve().parent.parent


class TestNSISBOM:
    """根因1: 缺UTF-8 BOM → CJK字符解析失败 → 乱码"""

    def test_file_has_utf8_bom(self):
        nsi = PROJECT / "meshctx_setup.nsi"
        assert nsi.exists(), "meshctx_setup.nsi 不存在"
        with open(nsi, "rb") as f:
            first_bytes = f.read(3)
        assert first_bytes == b'\xef\xbb\xbf', \
            f"缺少UTF-8 BOM! 当前: {first_bytes.hex()}. NSIS Unicode需要EF BB BF才能正确解析中日韩字符"


class TestNSISOrder:
    """根因2: MUI_PAGE在MUI_LANGUAGE之前 → LangString无法绑定 → 乱码"""

    def test_language_before_pages(self):
        nsi = PROJECT / "meshctx_setup.nsi"
        lines = _read_lines(nsi)
        lang_lines = []
        page_lines = []
        for i, line in enumerate(lines, 1):
            s = line.strip()
            if s.startswith('!insertmacro MUI_LANGUAGE '):
                lang_lines.append(i)
            elif s.startswith('!insertmacro MUI_PAGE_'):
                page_lines.append(i)

        assert lang_lines, "未找到 !insertmacro MUI_LANGUAGE"
        assert page_lines, "未找到 !insertmacro MUI_PAGE_*"

        last_lang = max(lang_lines)
        first_page = min(page_lines)
        assert last_lang > first_page, \
            f"MUI_LANGUAGE({last_lang}行)必须在MUI_PAGE({first_page}行)之后! NSIS要求页面宏在语言宏之前声明"

    def test_oninit_after_languages(self):
        """🔴 Bug#13: .onInit必须在MUI_LANGUAGE之后 — 否则语言选择对话框不显示"""
        nsi = PROJECT / "meshctx_setup.nsi"
        lines = _read_lines(nsi)
        lang_lines = []
        oninit_line = None
        for i, line in enumerate(lines, 1):
            s = line.strip()
            if s.startswith('!insertmacro MUI_LANGUAGE '):
                lang_lines.append(i)
            if s == 'Function .onInit':
                oninit_line = i
        assert oninit_line, "未找到 Function .onInit"
        last_lang = max(lang_lines)
        assert oninit_line > last_lang, \
            f".onInit({oninit_line}行)必须在MUI_LANGUAGE({last_lang}行)之后!"

    def test_unpage_confirm_before_instfiles(self):
        """卸载页: 确认对话框必须在卸载进度之前"""
        nsi = PROJECT / "meshctx_setup.nsi"
        lines = _read_lines(nsi)
        confirm_line = instfiles_line = None
        for i, line in enumerate(lines, 1):
            if '!insertmacro MUI_UNPAGE_CONFIRM' in line:
                confirm_line = i
            elif '!insertmacro MUI_UNPAGE_INSTFILES' in line:
                instfiles_line = i
        if confirm_line and instfiles_line:
            assert confirm_line < instfiles_line, \
                f"MUI_UNPAGE_CONFIRM({confirm_line})必须在MUI_UNPAGE_INSTFILES({instfiles_line})之前"


class TestLangStringCompleteness:
    """每组LangString必须覆盖全部7种语言"""

    LANGUAGES = {
        '1033': 'English', '2052': 'SimpChinese', '1041': 'Japanese',
        '1042': 'Korean', '1036': 'French', '1031': 'German', '1034': 'Spanish',
    }
    EXPECTED_GROUPS = [
        'WELCOME_TITLE', 'WELCOME_TEXT', 'DIR_TEXT',
        'INSTALLING', 'FINISH_TITLE', 'FINISH_TEXT',
        'FINISH_BUTTON',
    ]

    def test_langstring_groups_exist(self):
        nsi = PROJECT / "meshctx_setup.nsi"
        lines = _read_lines(nsi)
        groups = {}
        for line in lines:
            m = re.match(r'LangString (\w+) (\d{4})', line)
            if m:
                name, lcid = m.group(1), m.group(2)
                if name not in groups:
                    groups[name] = set()
                groups[name].add(lcid)

        for group in self.EXPECTED_GROUPS:
            assert group in groups, \
                f"缺少 LangString 组: {group}"

    def test_each_group_has_7_languages(self):
        nsi = PROJECT / "meshctx_setup.nsi"
        lines = _read_lines(nsi)
        groups = {}
        for line in lines:
            m = re.match(r'LangString (\w+) (\d{4})', line)
            if m:
                name, lcid = m.group(1), m.group(2)
                if name not in groups:
                    groups[name] = set()
                groups[name].add(lcid)

        expected_lcids = set(self.LANGUAGES.keys())
        for group in self.EXPECTED_GROUPS:
            lcids = groups.get(group, set())
            missing = expected_lcids - lcids
            assert not missing, \
                f"{group} 缺语言: {missing} → {', '.join(self.LANGUAGES[l] for l in missing)}"

    def test_no_extra_langstring_groups(self):
        """确保所有LangString组都被EXPECTED_GROUPS覆盖（新增组需同步更新预期）"""
        nsi = PROJECT / "meshctx_setup.nsi"
        lines = _read_lines(nsi)
        groups = set()
        for line in lines:
            m = re.match(r'LangString (\w+)', line)
            if m:
                groups.add(m.group(1))
        extra = groups - set(self.EXPECTED_GROUPS)
        assert not extra, \
            f"发现未预期的LangString组: {extra}. 请更新EXPECTED_GROUPS"


class TestVersionConsistency:
    """版本号必须在 .nsi / .spec / version_info.txt / __init__.py 中同步"""

    def test_nsi_version_matches_core(self):
        core_ver = _get_core_version()
        nsi_ver = _get_nsi_version()
        assert nsi_ver == core_ver, \
            f"meshctx_setup.nsi版本({nsi_ver}) != __init__.py版本({core_ver})"

    def test_spec_version_matches_core(self):
        core_ver = _get_core_version()
        spec_ver = _get_spec_version()
        assert spec_ver == core_ver, \
            f"meshctx_desktop.spec版本({spec_ver}) != __init__.py版本({core_ver})"

    def test_version_info_matches_core(self):
        core_ver = _get_core_version()
        vi_ver = _get_version_info_version()
        assert vi_ver == core_ver, \
            f"version_info.txt版本({vi_ver}) != __init__.py版本({core_ver})"


# ── Helpers ──────────────────────────────────────────────

def _read_lines(nsi_path: Path):
    with open(nsi_path, "r", encoding="utf-8-sig") as f:
        return f.readlines()


def _get_core_version() -> str:
    init = PROJECT / "src" / "core" / "__init__.py"
    text = init.read_text()
    m = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else "0.0.0"


def _get_nsi_version() -> str:
    nsi = PROJECT / "meshctx_setup.nsi"
    for line in _read_lines(nsi):
        m = re.search(r'!define VERSION "([^"]+)"', line)
        if m:
            return m.group(1)
    return "0.0.0"


def _get_spec_version() -> str:
    spec = PROJECT / "meshctx_desktop.spec"
    text = spec.read_text()
    m = re.search(r'CFBundleShortVersionString.*?[\'"]([\d.]+)[\'"]', text)
    return m.group(1) if m else "0.0.0"


def _get_version_info_version() -> str:
    vi = PROJECT / "version_info.txt"
    text = vi.read_text()
    m = re.search(r"StringStruct\(u'FileVersion', u'([^']+)'\)", text)
    return m.group(1) if m else "0.0.0"


# ═══════════════════════════════════════════════════════
# 🔴 回归: spec必须包含全部核心模块 (防ModuleNotFoundError)
# 这个问题已出现4次: metacognition等模块在exe中缺失
# ═══════════════════════════════════════════════════════
class TestSpecModuleCoverage:
    """验证spec.hiddenimports包含全部src.core模块"""

    def test_all_core_modules_in_spec(self):
        """每个src/core/*.py都必须在spec的hiddenimports中"""
        from pathlib import Path
        core_dir = PROJECT / "src" / "core"
        actual_modules = sorted([
            f.stem for f in core_dir.glob("*.py")
            if f.stem != "__init__" and not f.name.startswith("_")
        ])

        spec_text = (PROJECT / "meshctx_desktop.spec").read_text()
        missing = []
        for mod in actual_modules:
            full_name = f"src.core.{mod}"
            if full_name not in spec_text:
                missing.append(mod)

        assert not missing, (
            f"🔴 {len(missing)} 模块在spec hiddenimports中缺失! "
            f"这会导致Windows exe启动时ModuleNotFoundError!\n"
            f"缺失: {missing}\n"
            f"修复: 在meshctx_desktop.spec hiddenimports中添加这些模块"
        )

    def test_collect_submodules_in_spec(self):
        """spec必须使用collect_submodules作为第一道防线"""
        spec_text = (PROJECT / "meshctx_desktop.spec").read_text()
        assert "collect_submodules('src.core')" in spec_text, (
            "spec缺少collect_submodules('src.core') — 这是自动发现模块的防线"
        )

    def test_spec_has_no_duplicate_modules(self):
        """hiddenimports不能有重复模块"""
        import re
        spec_text = (PROJECT / "meshctx_desktop.spec").read_text()
        modules = re.findall(r"'src\.core\.(\w+)'", spec_text)
        duplicates = [m for m in modules if modules.count(m) > 1]
        assert not set(duplicates), (
            f"spec hiddenimports中有重复模块: {set(duplicates)}"
        )
