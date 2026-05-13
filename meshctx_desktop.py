#!/usr/bin/env python3
"""
meshctx Desktop — All-in-One 桌面客户端
pywebview + FastAPI + 系统托盘
Windows/macOS/Linux 三平台
"""
import sys, os, threading, time, logging, traceback
from pathlib import Path

# ── 日志文件（PyInstaller模式下也可见）─────────────────
LOG_DIR = Path.home() / ".meshctx" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / "desktop.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger("meshctx.desktop")

# ── 全局配置 ─────────────────────────────────────────
PORT = int(os.environ.get("MESHCTX_PORT", "3000"))
HOST = "127.0.0.1"
TITLE = "meshctx Desktop v1.5"

# 路径（兼容 PyInstaller 冻结模式）
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
    for i in range(timeout * 2):
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
        logger.info("meshctx Desktop v1.5 启动中...")
        logger.info(f"Python: {sys.version}")
        logger.info(f"Frozen: {getattr(sys, 'frozen', False)}")
        logger.info(f"Log: {LOG_FILE}")

        PORT = find_free_port(PORT)
        app_url = f"http://{HOST}:{PORT}/ui/desktop"

        # 1. 启动后台服务器
        logger.info(f"启动 FastAPI: {HOST}:{PORT}")
        start_server(PORT)

        # 2. 等待就绪
        health_url = f"http://{HOST}:{PORT}/health"
        if not wait_for_server(health_url):
            logger.error(f"服务器启动超时! 检查 {LOG_FILE}")
            print(f"\n❌ 服务器启动失败，请查看日志: {LOG_FILE}\n")
            input("按 Enter 退出...")
            sys.exit(1)
        logger.info("服务器就绪 ✓")

        # 3. 打开桌面窗口
        try:
            import webview
            logger.info("创建桌面窗口...")
            window = webview.create_window(
                title=TITLE, url=app_url,
                width=1280, height=820,
                resizable=True, min_size=(800, 600),
            )
            logger.info(f"窗口已打开: {app_url}")
            webview.start(debug=False)
        except ImportError:
            logger.error("pywebview 未安装!")
            print(f"\n❌ pywebview 未安装。请在浏览器打开: {app_url}\n")
            import webbrowser
            webbrowser.open(app_url)
            input("按 Enter 退出...")
        except Exception as e:
            logger.error(f"窗口启动失败: {traceback.format_exc()}")
            print(f"\n❌ 窗口启动失败: {e}")
            print(f"   请在浏览器打开: {app_url}")
            print(f"   日志: {LOG_FILE}\n")
            import webbrowser
            webbrowser.open(app_url)
            input("按 Enter 退出...")

    except Exception as e:
        logger.error(f"致命错误: {traceback.format_exc()}")
        print(f"\n❌ 启动失败: {e}\n日志: {LOG_FILE}\n")
        input("按 Enter 退出...")


if __name__ == "__main__":
    main()
