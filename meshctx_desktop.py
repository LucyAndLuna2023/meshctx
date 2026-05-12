#!/usr/bin/env python3
"""
meshctx Desktop — All-in-One 桌面客户端
pywebview 原生窗口 + FastAPI 后台 + 系统托盘
双击即用，无需浏览器。跨平台: Windows/macOS/Linux
"""
import sys
import os
import threading
import time
import signal
import logging
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("meshctx.desktop")

# ── 配置 ─────────────────────────────────────────────
PORT = 3000
HOST = "127.0.0.1"
APP_URL = f"http://{HOST}:{PORT}/ui/"
TITLE = "meshctx Desktop"
WIDTH, HEIGHT = 1280, 820

# Logo 路径 (PyInstaller打包后相对于 _MEIPASS)
if getattr(sys, 'frozen', False):
    BASE_DIR = Path(sys._MEIPASS)
else:
    BASE_DIR = Path(__file__).resolve().parent
LOGO_PATH = BASE_DIR / "logo.png"
LOGO_ICO = BASE_DIR / "logo.ico"


def find_free_port(start=3000, max_tries=10):
    """找一个空闲端口"""
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
    """在后台线程启动 FastAPI 服务器"""
    import asyncio

    async def serve():
        import uvicorn
        config = uvicorn.Config(
            "src.main:app",
            host=HOST,
            port=port,
            log_level="warning",
            loop="asyncio",
        )
        server = uvicorn.Server(config)
        await server.serve()

    def run():
        asyncio.run(serve())

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    time.sleep(1.5)
    return thread


def wait_for_server(url, timeout=10):
    """等待服务器就绪"""
    import urllib.request
    for _ in range(timeout * 2):
        try:
            urllib.request.urlopen(url, timeout=1)
            return True
        except Exception:
            time.sleep(0.5)
    return False


# ── 系统托盘 ─────────────────────────────────────────
def create_tray(webview_window):
    """创建系统托盘图标 (可选)"""
    try:
        import pystray
        from PIL import Image
        if not LOGO_PATH.exists():
            return None
        image = Image.open(LOGO_PATH).resize((32, 32))
        menu = pystray.Menu(
            pystray.MenuItem("Show", lambda: (webview_window.show(), webview_window.restore()), default=True),
            pystray.MenuItem("Hide", lambda: webview_window.hide()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda: os._exit(0)),
        )
        icon = pystray.Icon("meshctx", image, TITLE, menu)
        threading.Thread(target=icon.run, daemon=True).start()
        return icon
    except Exception:
        return None


# ── 主入口 ───────────────────────────────────────────
def main():
    global PORT
    PORT = find_free_port(PORT)
    app_url = f"http://{HOST}:{PORT}/ui/"

    print(f"""
╔══════════════════════════════════════╗
║       🧠 meshctx Desktop            ║
║       v1.3.0 All-in-One Client      ║
╠══════════════════════════════════════╣
║  启动服务器: {HOST}:{PORT}
║  窗口即将打开...
╚══════════════════════════════════════╝
    """)

    # 1. 启动后台服务器
    logger.info(f"Starting FastAPI: {HOST}:{PORT}")
    server_thread = start_server(PORT)

    # 2. 等待服务器就绪
    health_url = f"http://{HOST}:{PORT}/health"
    if not wait_for_server(health_url):
        # GUI模式下用messagebox报错
        try:
            import webview as wv
            wv.windows[0].destroy() if wv.windows else None
        except:
            pass
        logger.error("Server failed to start!")
        sys.exit(1)
    logger.info("Server ready")

    # 3. 打开桌面窗口
    icon_path = str(LOGO_ICO) if LOGO_ICO.exists() else None

    try:
        import webview
        window = webview.create_window(
            title=TITLE,
            url=app_url,
            width=WIDTH,
            height=HEIGHT,
            resizable=True,
            min_size=(800, 600),
        )
        tray_icon = create_tray(window)
        logger.info("Starting desktop window...")
        webview.start(debug=False)
    except ImportError:
        logger.error("pywebview not installed. Opening browser instead.")
        import webbrowser
        webbrowser.open(app_url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    logger.info("meshctx Desktop 已退出")


if __name__ == "__main__":
    main()
