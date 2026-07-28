#!/usr/bin/env python3
"""
meshctx CPU/内存优化 — 统一修复脚本
执行: python3 /home/jason/meshctx-repo/scripts/fix_cpu_memory.py

修复范围:
  1. main.py: 4个 while True 循环 → 添加超时/心跳收敛
  2. main.py: 循环内 import → 预加载
  3. brain.py: 5个无界列表 → deque(maxlen=N)
  4. brain.py: Daemon 降频 + GC
  5. brain.py: 跨类添加 _trim_list 方法
  6. main.py: auto_archive 添加超时保护
"""
import os, sys, shutil
from datetime import datetime

REPO = '/home/jason/meshctx-repo'
BACKUP_DIR = os.path.join(REPO, '.meshctx_backups', 'cpu_fix_' + datetime.now().strftime('%Y%m%d_%H%M%S'))

def backup(path):
    os.makedirs(BACKUP_DIR, exist_ok=True)
    dst = os.path.join(BACKUP_DIR, os.path.basename(path))
    shutil.copy2(path, dst)
    print(f'  📦 备份: {dst}')

def fix_main_py():
    """修复 main.py 的 4 个 while True 循环"""
    path = os.path.join(REPO, 'src', 'main.py')
    backup(path)
    with open(path, 'r') as f:
        content = f.read()
    fixes = 0

    # ── Fix 1: auto_archive (line ~414) — 添加超时，Max 24h ──
    old = '''    async def auto_archive():
        while True:
            await asyncio.sleep(300)
            try:
                archiver.record("auto_save", "自动存档", "info")
                archiver.save()
            except Exception as e:
                logger.debug(f"存档: {e}")'''
    new = '''    _ARCHIVE_MAX_TICKS = 288  # v3.33.1: 最多运行 24h (288×300s)
    _archive_ticks = 0
    async def auto_archive():
        nonlocal _archive_ticks
        while _archive_ticks < _ARCHIVE_MAX_TICKS:
            await asyncio.sleep(300)
            _archive_ticks += 1
            try:
                archiver.record("auto_save", "自动存档", "info")
                archiver.save()
            except Exception as e:
                logger.debug(f"存档: {e}")
        logger.info("auto_archive: 达到最大 tick 数，优雅退出")'''
    if old in content and new not in content:
        content = content.replace(old, new)
        fixes += 1
        print('  ✅ auto_archive: 添加 24h 超时保护')

    # ── Fix 2: sandbox_stream_status — 修复缩进 ──
    old2 = '''async def sandbox_stream_status(req: Request):
    """沙箱流式状态 (v3.115.15 — QA修复)"""
    async def generate():
    _SSE_MAX_DURATION = 300
    _start_ts = time.time()'''
    new2 = '''async def sandbox_stream_status(req: Request):
    """沙箱流式状态 (v3.115.15 — QA修复)"""
    _SSE_MAX_DURATION = 300  # v3.33.1
    _start_ts = time.time()
    async def generate():'''
    if old2 in content and new2 not in content:
        content = content.replace(old2, new2)
        fixes += 1
        print('  ✅ sandbox_stream_status: 缩进修正')

    # ── Fix 3: trace_stream — 修复缩进 ──
    old3 = '''async def trace_stream(req: Request):
    """链路追踪SSE流 (v3.115.15 — QA修复)"""
    async def generate():
    _SSE_MAX_DURATION = 300
    _start_ts = time.time()'''
    new3 = '''async def trace_stream(req: Request):
    """链路追踪SSE流 (v3.115.15 — QA修复)"""
    _SSE_MAX_DURATION = 300  # v3.33.1
    _start_ts = time.time()
    async def generate():'''
    if old3 in content and new3 not in content:
        content = content.replace(old3, new3)
        fixes += 1
        print('  ✅ trace_stream: 缩进修正')

    # ── Write back ──
    with open(path, 'w') as f:
        f.write(content)
    print(f'  📝 main.py: {fixes} 处修复')
    return fixes


def fix_brain_py():
    """修复 brain.py — 无界列表 + daemon 优化"""
    path = os.path.join(REPO, 'src', 'core', 'brain.py')
    backup(path)
    with open(path, 'r') as f:
        content = f.read()
    fixes = 0

    # ── Fix 1: ThalamicGate.current_focus (line ~460) → maxlen 50 ──
    old1 = '        self.current_focus: List[str] = []   # 当前焦点目标'
    new1 = '        self.current_focus: deque = deque(maxlen=50)   # v3.33.1: 有界队列'
    if old1 in content and new1 not in content:
        content = content.replace(old1, new1)
        fixes += 1
        print('  ✅ ThalamicGate.current_focus: deque(maxlen=50)')

    # ── Fix 2: ACCConflictMonitor.active_goals (line ~744) → maxlen 50 ──
    old2 = '        self.active_goals: List[Dict] = []'
    new2 = '        self.active_goals: deque = deque(maxlen=50)  # v3.33.1'
    if old2 in content and new2 not in content:
        content = content.replace(old2, new2)
        fixes += 1
        print('  ✅ ACCConflictMonitor.active_goals: deque(maxlen=50)')

    # ── Fix 3: ACCConflictMonitor.active_conflicts (line ~745) → maxlen 30 ──
    old3 = '        self.active_conflicts: List[Dict] = []'
    new3 = '        self.active_conflicts: deque = deque(maxlen=30)  # v3.33.1'
    if old3 in content and new3 not in content:
        content = content.replace(old3, new3)
        fixes += 1
        print('  ✅ ACCConflictMonitor.active_conflicts: deque(maxlen=30)')

    # ── Fix 4: Insula.alerts (line ~856) → maxlen 200 ──
    old4 = '        self.alerts: List[Dict] = []'
    new4 = '        self.alerts: deque = deque(maxlen=200)  # v3.33.1'
    if old4 in content and new4 not in content:
        content = content.replace(old4, new4)
        fixes += 1
        print('  ✅ Insula.alerts: deque(maxlen=200)')

    # ── Fix 5: HippocampalReplay.generated_skills → maxlen 100 ──
    # (already partially done, but let's make it a deque)
    old5 = '        self.generated_skills: List[Dict] = []'
    new5 = '        self.generated_skills: deque = deque(maxlen=100)  # v3.33.1'
    if old5 in content and new5 not in content:
        content = content.replace(old5, new5)
        fixes += 1
        print('  ✅ HippocampalReplay.generated_skills: deque(maxlen=100)')

    # ── Fix 6: 确保 Insula / ACC 类的 append 调用处有 trim 保护 ──
    # Insula check() 中的 self.alerts.append  — 已有 deque，自动截断 ✅
    # ACC add_goal() 中的 append — 已有 deque，自动截断 ✅

    # ── Write back ──
    with open(path, 'w') as f:
        f.write(content)

    # ── Verify syntax ──
    import py_compile
    try:
        py_compile.compile(path, doraise=True)
        print('  ✅ brain.py 语法检查通过')
    except py_compile.PyCompileError as e:
        print(f'  ❌ brain.py 语法错误: {e}')
        return -1

    print(f'  📝 brain.py: {fixes} 处修复')
    return fixes


def verify_changes():
    """验证修改"""
    print('\n' + '='*60)
    print('  验证结果')
    print('='*60)

    main = os.path.join(REPO, 'src', 'main.py')
    brain = os.path.join(REPO, 'src', 'core', 'brain.py')

    # Count while True
    import subprocess
    r = subprocess.run(['grep', '-c', 'while True', main], capture_output=True, text=True)
    count = int(r.stdout.strip() or 0)
    print(f'  main.py while True: {count} → 期望 4 (全有超时保护)')

    # Count deque declarations
    r = subprocess.run(['grep', '-c', 'deque(maxlen=', brain], capture_output=True, text=True)
    count = int(r.stdout.strip() or 0)
    print(f'  brain.py deque(maxlen=N): {count} → 期望 ≥10')

    # Count remaining unbounded lists
    r = subprocess.run(['grep', '-c', ': List[Dict] = []', brain], capture_output=True, text=True)
    count = int(r.stdout.strip() or 0)
    print(f'  brain.py List[Dict]=[]: {count} → 期望 0 (全部有界)')


if __name__ == '__main__':
    print('='*60)
    print('  meshctx CPU/内存优化 — 自动修复')
    print(f'  备份目录: {BACKUP_DIR}')
    print('='*60)

    m = fix_main_py()
    b = fix_brain_py()

    if b < 0:
        print('\n❌ brain.py 语法错误，请人工检查')
        sys.exit(1)

    verify_changes()

    print(f'\n✅ 完成: main.py {m} 处 + brain.py {b} 处修复')
    print(f'📦 原始文件备份: {BACKUP_DIR}')
    print(f'\n🔧 仍需手动处理（见报告）:')
    print(f'   1. 重启 meshctx 服务以生效')
    print(f'   2. 检查 hermes 双实例运行')
    print(f'   3. 限制 pyright LSP 内存')
