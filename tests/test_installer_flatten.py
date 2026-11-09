# -*- coding: utf-8 -*-
"""安装脚本拍平块行为级回归 (002codex B1-B3 / 004zcode 对抗面 a-d)."""
import os, re, shutil, subprocess, pathlib, tempfile, pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ["install-mac.sh", "install.sh"]


def _flatten_block(script_text):
    m = re.search(r"(    # ── BEGIN FLATTEN.*?    # ── END FLATTEN ──)", script_text, re.S)
    assert m, "FLATTEN 块未找到"
    return m.group(1)


def _run_flatten(script, install_dir, version="3.137.22"):
    """提取 FLATTEN 块在沙箱内执行 (替代变量注入 VERSION/INSTALL_DIR)."""
    script_text = (ROOT / script).read_text(encoding="utf-8")
    block = _flatten_block(script_text)
    driver = f'''
VERSION="{version}"
INSTALL_DIR="{install_dir}"
RED=""; GREEN=""; YELLOW=""; CYAN=""; NC=""
{block}
'''
    r = subprocess.run(["bash", "-c", driver], capture_output=True, text=True, timeout=60)
    return r


def _mk_extracted(install, version="3.137.22"):
    """模拟 tarball 解压目录 (repo 文件: src/ + pyproject.toml)."""
    sub = os.path.join(install, "meshctx-" + version)
    os.makedirs(os.path.join(sub, "src", "core"), exist_ok=True)
    open(os.path.join(sub, "pyproject.toml"), "w").write(f'version = "{version}"\n')
    init = os.path.join(sub, "src", "__init__.py")
    open(init, "w").write(f'__version__ = "{version}"\n')
    open(os.path.join(sub, "src", "main.py"), "w").write("pass\n")
    return sub


@pytest.mark.parametrize("script", SCRIPTS)
def test_upgrade_scenario_merges_and_version_ok(script):
    """升级场景 (既有 venv/data/src 旧目录共存): 合并拍平 + 版本一致性自检过."""
    t = tempfile.mkdtemp()
    inst = os.path.join(t, ".meshctx")
    # 既有旧环境
    os.makedirs(os.path.join(inst, "venv", "bin"))
    os.makedirs(os.path.join(inst, "data"))
    os.makedirs(os.path.join(inst, "src"))
    open(os.path.join(inst, "src", "__init__.py"), "w").write('__version__ = "3.100.0"\n')  # 旧 payload
    open(os.path.join(inst, "config.yaml"), "w").write("keep: true\n")  # 用户数据不被破坏
    # 解压目录 (新版本 3.137.22)
    sub = _mk_extracted(inst, "3.137.22")
    r = _run_flatten(script, inst, "3.137.22")
    assert r.returncode == 0, f"exit={r.returncode}\n{r.stdout}\n{r.stderr}"
    # 合并验证: 新 payload 覆盖旧 src
    init = open(os.path.join(inst, "src", "__init__.py")).read()
    assert '3.137.22' in init, "src payload 未被新版覆盖 (静默旧版)"
    assert os.path.isfile(os.path.join(inst, "pyproject.toml"))
    # 解压目录已移除
    assert not os.path.isdir(sub), "解压目录残留"
    # 用户数据未被破坏
    assert open(os.path.join(inst, "config.yaml")).read() == "keep: true\n"
    assert os.path.isdir(os.path.join(inst, "venv"))
    shutil.rmtree(t)


@pytest.mark.parametrize("script", SCRIPTS)
def test_multiple_candidates_fail_closed(script):
    """多 meshctx-* 候选无版本匹配 → fail-closed (002codex B1)."""
    t = tempfile.mkdtemp()
    inst = os.path.join(t, ".meshctx")
    for d in ("meshctx-3.100.0", "meshctx-core", "meshctx-unknown"):
        os.makedirs(os.path.join(inst, d))
    r = _run_flatten(script, inst, "3.137.22")
    assert r.returncode == 1, f"多候选应 fail-closed, 实际 exit={r.returncode}\n{r.stdout}"
    shutil.rmtree(t)


@pytest.mark.parametrize("script", SCRIPTS)
def test_version_mismatch_fails_loud(script):
    """合并后 payload 版本 ≠ 安装版本 → 红字退出 (防静默旧版; 004zcode 探针 [3])."""
    t = tempfile.mkdtemp()
    inst = os.path.join(t, ".meshctx")
    os.makedirs(os.path.join(inst, "src"))
    open(os.path.join(inst, "src", "__init__.py"), "w").write('__version__ = "3.100.0"\n')
    sub = _mk_extracted(inst, "3.137.22")
    # 篡改解压目录 payload 为旧版 → 合并后自检必须红
    open(os.path.join(sub, "src", "__init__.py"), "w").write('__version__ = "3.100.0"\n')
    r = _run_flatten(script, inst, "3.137.22")
    assert r.returncode == 1, f"版本不一致应红字退出, 实际 exit={r.returncode}\n{r.stdout}"
    shutil.rmtree(t)


@pytest.mark.parametrize("script", SCRIPTS)
def test_flat_tarball_skips_flatten(script):
    """tar 平铺 (顶层 pyproject 直接存在) → 跳过拍平不报错."""
    t = tempfile.mkdtemp()
    inst = os.path.join(t, ".meshctx")
    os.makedirs(os.path.join(inst, "src"))
    open(os.path.join(inst, "pyproject.toml"), "w").write('version = "3.137.22"\n')
    open(os.path.join(inst, "src", "__init__.py"), "w").write('__version__ = "3.137.22"\n')
    r = _run_flatten(script, inst, "3.137.22")
    assert r.returncode == 0, f"平铺场景不应报错: {r.stdout}\n{r.stderr}"
    shutil.rmtree(t)
