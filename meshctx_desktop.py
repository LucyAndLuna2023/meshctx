#!/usr/bin/env python3
"""
meshctx Desktop — All-in-One 桌面客户端
pywebview + FastAPI + 系统托盘
Windows/macOS/Linux 三平台
"""
import sys, os, threading, time, logging, traceback
from pathlib import Path

# ── 检测GUI模式 ────────────────────────────────────
GUI_MODE = getattr(sys, 'frozen', False) and sys.platform == 'win32'

# ── 日志（仅文件，GUI模式不用stdout）─────────────────
LOG_DIR = Path.home() / ".meshctx" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "desktop.log"

_handlers = [logging.FileHandler(LOG_FILE, encoding='utf-8')]
if not GUI_MODE:
    _handlers.append(logging.StreamHandler(sys.stdout))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", handlers=_handlers)
logger = logging.getLogger("meshctx.desktop")

# ── GUI弹窗 ─────────────────────────────────────────
def _alert(title, msg):
    """弹窗提示，不依赖console"""
    try:
        if sys.platform == 'win32':
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, str(msg), str(title), 0x40)
        else:
            # macOS/Linux: 尝试osascript/zenity
            os.system(f'osascript -e \'display notification "{msg}" with title "{title}"\' 2>/dev/null')
    except Exception:
        pass
    logger.error(f"{title}: {msg}")

def _safe_pause():
    """GUI模式直接退出，无console可停留"""
    if GUI_MODE:
        time.sleep(3)  # 给用户3秒看弹窗
    else:
        try:
            input("按 Enter 退出...")
        except (EOFError, OSError):
            pass

# ── 全局配置 ─────────────────────────────────────────
PORT = int(os.environ.get("MESHCTX_PORT", "3000"))
HOST = "127.0.0.1"
TITLE = "meshctx Desktop v3.33.0"

if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).resolve().parent
LOGO_ICO = BASE_DIR / "logo.ico"


def find_free_port(start=3000, max_tries=20):
    import socket
    for port in range(start, start + max_tries):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    return start


def start_server(port):
    import asyncio
    async def serve():
        import uvicorn
        config = uvicorn.Config("src.main:app", host=HOST, port=port,
                                log_level="warning", loop="asyncio")
        await uvicorn.Server(config).serve()
    t = threading.Thread(target=lambda: asyncio.run(serve()), daemon=True)
    t.start()
    time.sleep(2)
    return t


def wait_for_server(url, timeout=15):
    import urllib.request
    for _ in range(timeout * 2):
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


def main():
    global PORT
    try:
        logger.info("=" * 50)
        logger.info(f"meshctx Desktop v3.33.0 启动中...")
        logger.info(f"Python: {sys.version} | Frozen: {getattr(sys, 'frozen', False)} | GUI: {GUI_MODE}")
        logger.info(f"Log: {LOG_FILE}")

        PORT = find_free_port(PORT)
        app_url = f"http://{HOST}:{PORT}/ui/desktop"

        # 1. 启动后台服务器
        logger.info(f"启动 FastAPI: {HOST}:{PORT}")
        start_server(PORT)

        # 2. 等待就绪
        health_url = f"http://{HOST}:{PORT}/health"
        if not wait_for_server(health_url):
            msg = f"服务器启动超时\n请查看日志: {LOG_FILE}"
            logger.error(msg)
            _alert("meshctx 启动失败", msg)
            _safe_pause()
            sys.exit(1)
        logger.info("服务器就绪")

        # 3. 打开浏览器
        import webbrowser
        webbrowser.open(app_url)
        logger.info(f"浏览器已打开: {app_url}")

        # 4. 保持运行 — 等待用户关闭或无限循环
        logger.info("meshctx Desktop 运行中，关闭窗口或Ctrl+C退出...")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("用户中断")

    except Exception as e:
        logger.error(f"致命错误: {traceback.format_exc()}")
        _alert("meshctx 错误", f"启动失败: {e}\n日志: {LOG_FILE}")
        _safe_pause()


if __name__ == "__main__":
    main()
