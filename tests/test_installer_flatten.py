# -*- coding: utf-8 -*-
"""安装脚本拍平块行为级回归 v2 (002codex 真实 tarball 复现 + staging 预检)."""
import os, re, shutil, subprocess, pathlib, tempfile, pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ["install-mac.sh", "install.sh"]
VERSION = "3.137.23"


def _flatten_block(script_text):
    m = re.search(r"(    # ── BEGIN FLATTEN.*?    # ── END FLATTEN ──)", script_text, re.S)
    assert m, "FLATTEN 块未找到"
    return m.group(1)


def _run_flatten(script, install_dir, version=VERSION):
    script_text = (ROOT / script).read_text(encoding="utf-8")
    block = _flatten_block(script_text)
    driver = f'''
VERSION="{version}"
INSTALL_DIR="{install_dir}"
RED=""; GREEN=""; YELLOW=""; CYAN=""; NC=""
{block}
'''
    return subprocess.run(["bash", "-c", driver], capture_output=True, text=True, timeout=120)


def _mk_candidate(install, dirname, version):
    """构造候选目录 (真实 tarball 形态: src/ + pyproject.toml)."""
    sub = os.path.join(install, dirname)
    os.makedirs(os.path.join(sub, "src", "core"), exist_ok=True)
    open(os.path.join(sub, "pyproject.toml"), "w").write(f'version = "{version}"\n')
    open(os.path.join(sub, "src", "__init__.py"), "w").write(f'__version__ = "{version}"\n')
    open(os.path.join(sub, "src", "main.py"), "w").write("pass\n")
    return sub


@pytest.mark.parametrize("script", SCRIPTS)
def test_real_sha_single_candidate(script):
    """真实 tarball 形态: 顶层 = meshctx-<commit SHA> (无版本号) — 按内容识别并合并."""
    t = tempfile.mkdtemp()
    inst = os.path.join(t, ".meshctx")
    sub = _mk_candidate(inst, "meshctx-" + SHA_DIRNAME_STUB, VERSION)
    r = _run_flatten(script, inst)
    assert r.returncode == 0, f"{r.stdout}\n{r.stderr}"
    assert "content-identified" in r.stdout
    init = open(os.path.join(inst, "src", "__init__.py")).read()
    assert VERSION in init
    assert not os.path.isdir(sub)
    shutil.rmtree(t)


# GitHub tarball 顶层目录名 = meshctx-<commit SHA>, 用 12 位 stub 代表
SHA_DIRNAME_STUB = "a1b2c3d4e5f6"


@pytest.mark.parametrize("script", SCRIPTS)
def test_real_sha_double_candidate_retry_path(script):
    """002codex B1 核心场景: .21 失败残留 + .22 重装 → 两个 meshctx-<SHA> 目录并存.
    旧版按 ${VERSION} 名称匹配永远不命中 → 升级不可完成. 新版按内容识别选 .22."""
    t = tempfile.mkdtemp()
    inst = os.path.join(t, ".meshctx")
    _mk_candidate(inst, "meshctx-aaa111bbb222", "3.137.21")   # 失败残留
    sub22 = _mk_candidate(inst, "meshctx-ccc333ddd444", VERSION)
    # 既有用户数据
    os.makedirs(os.path.join(inst, "venv"))
    os.makedirs(os.path.join(inst, "data"))
    open(os.path.join(inst, "config.yaml"), "w").write("keep: true\n")
    r = _run_flatten(script, inst)
    assert r.returncode == 0, f"失败重试路径应可完成升级: {r.stdout}\n{r.stderr}"
    init = open(os.path.join(inst, "src", "__init__.py")).read()
    assert VERSION in init, "升级后 payload 应为新版"
    assert "3.137.21" not in init, "旧版残留"
    assert not os.path.isdir(sub22), "选中候选应已合并移除"
    # 用户数据零破坏
    assert open(os.path.join(inst, "config.yaml")).read() == "keep: true\n"
    assert os.path.isdir(os.path.join(inst, "venv"))
    shutil.rmtree(t)


@pytest.mark.parametrize("script", SCRIPTS)
def test_no_candidate_matching_version_fails_closed(script):
    """无候选内容匹配 VERSION → fail-closed 列印候选版本 (002codex B1 反面)."""
    t = tempfile.mkdtemp()
    inst = os.path.join(t, ".meshctx")
    _mk_candidate(inst, "meshctx-aaa111", "3.137.21")
    _mk_candidate(inst, "meshctx-bbb222", "3.137.21")
    r = _run_flatten(script, inst, "3.137.21+wrong")  # VERSION 不存在
    assert r.returncode == 1, "无匹配候选应 fail-closed"
    shutil.rmtree(t)


@pytest.mark.parametrize("script", SCRIPTS)
def test_staging_zero_sideeffect_on_mismatch(script):
    """002codex B2: 候选内容不匹配 → 合并不发生/候选保留/安装根不污染 (零副作用)."""
    t = tempfile.mkdtemp()
    inst = os.path.join(t, ".meshctx")
    # 安装根只有用户数据 (无旧 src)
    os.makedirs(os.path.join(inst, "venv"))
    sub = _mk_candidate(inst, "meshctx-wrongver123", "3.100.0")
    r = _run_flatten(script, inst, "3.137.23")
    assert r.returncode == 1
    # 零副作用: 候选保留 (未删), 安装根无 src 污染
    assert os.path.isdir(sub), "候选目录不应被删除"
    assert not os.path.exists(os.path.join(inst, "src", "__init__.py")), "安装根不应被污染"
    shutil.rmtree(t)


@pytest.mark.parametrize("script", SCRIPTS)
def test_pyproject_metadata_mismatch_fails(script):
    """002codex: metadata 与 payload 需同版 — metadata 不符的候选不应被选中."""
    t = tempfile.mkdtemp()
    inst = os.path.join(t, ".meshctx")
    sub = os.path.join(inst, "meshctx-xyz789")
    os.makedirs(os.path.join(sub, "src"))
    open(os.path.join(sub, "pyproject.toml"), "w").write('version = "3.100.0"\n')  # metadata 旧
    open(os.path.join(sub, "src", "__init__.py"), "w").write(f'__version__ = "{VERSION}"\n')  # payload 新
    open(os.path.join(sub, "src", "main.py"), "w").write("pass\n")
    r = _run_flatten(script, inst)
    assert r.returncode == 1, "metadata≠VERSION 的候选不应被内容识别选中"
    # 安装根未被污染
    assert not os.path.exists(os.path.join(inst, "src", "__init__.py"))
    shutil.rmtree(t)


@pytest.mark.parametrize("script", SCRIPTS)
def test_flat_tarball_skips_flatten(script):
    """tar 平铺 (顶层 pyproject 直接存在) → 跳过拍平不报错."""
    t = tempfile.mkdtemp()
    inst = os.path.join(t, ".meshctx")
    os.makedirs(os.path.join(inst, "src"))
    open(os.path.join(inst, "pyproject.toml"), "w").write(f'version = "{VERSION}"\n')
    open(os.path.join(inst, "src", "__init__.py"), "w").write(f'__version__ = "{VERSION}"\n')
    r = _run_flatten(script, inst)
    assert r.returncode == 0, f"平铺场景不应报错: {r.stdout}\n{r.stderr}"
    shutil.rmtree(t)


def test_no_orphan_mv_block():
    """002codex: install.sh END FLATTEN 后的旧 mv 死代码必须清除."""
    for script in SCRIPTS:
        s = (ROOT / script).read_text(encoding="utf-8")
        m = re.search(r"# ── END FLATTEN ──(.*?)(?:\n#|\nfi)", s, re.S)
        assert m, "END FLATTEN 锚未找到"
        tail = m.group(1)
        assert "mv \"${_SUBDIR}\"" not in tail, f"{script}: END FLATTEN 后残留旧 mv 死代码"
