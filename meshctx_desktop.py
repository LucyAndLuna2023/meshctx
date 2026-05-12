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
    """创建系统托盘图标 (可选, 需要 pystray)"""
    try:
        import pystray
        from PIL import Image

        if not LOGO_PATH.exists():
            logger.warning(f"Logo not found: {LOGO_PATH}")
            return None

        image = Image.open(LOGO_PATH)
        image = image.resize((32, 32))

        def on_show(icon, item):
            webview_window.show()
            webview_window.restore()

        def on_hide(icon, item):
            webview_window.hide()

        def on_quit(icon, item):
            icon.stop()
            os._exit(0)

        menu = pystray.Menu(
            pystray.MenuItem("显示窗口", on_show, default=True),
            pystray.MenuItem("隐藏到托盘", on_hide),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", on_quit),
        )

        icon = pystray.Icon("meshctx", image, TITLE, menu)

        def run_tray():
            icon.run()

        tray_thread = threading.Thread(target=run_tray, daemon=True)
        tray_thread.start()
        logger.info("系统托盘已创建")
        return icon
    except ImportError:
        logger.info("pystray 未安装，跳过托盘")
        return None
    except Exception as e:
        logger.warning(f"托盘创建失败: {e}")
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
    logger.info(f"启动 FastAPI 服务器: {HOST}:{PORT}")
    server_thread = start_server(PORT)

    # 2. 等待服务器就绪
    if not wait_for_server(f"http://{HOST}:{PORT}/health"):
        logger.error("服务器启动超时！")
        sys.exit(1)
    logger.info("服务器就绪 ✓")

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
            fullscreen=False,
            min_size=(800, 600),
            confirm_close=True,
        )

        # 4. 系统托盘 (可选)
        tray_icon = create_tray(window)

        # 5. 启动主循环
        logger.info("启动桌面窗口...")
        webview.start(debug=False)

    except ImportError:
        logger.error("pywebview 未安装。运行: pip install pywebview")
        logger.info(f"请在浏览器中打开: {app_url}")
        # 回退: 直接在浏览器打开
        import webbrowser
        webbrowser.open(app_url)
        # 保持运行
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    except Exception as e:
        logger.error(f"窗口启动失败: {e}")
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
