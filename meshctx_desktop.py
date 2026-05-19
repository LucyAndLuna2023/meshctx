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
TITLE = "meshctx Desktop v2.25.0"

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


def enable_autostart():
    """启用开机自启动 (PRD §3.1-3.3)"""
    import platform
    system = platform.system()
    try:
        if system == "Windows":
            import winreg
            key = winreg.HKEY_CURRENT_USER
            subkey = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(key, subkey, 0, winreg.KEY_SET_VALUE) as reg:
                exe_path = sys.executable if not getattr(sys, 'frozen', False) else sys.argv[0]
                winreg.SetValueEx(reg, "meshctx", 0, winreg.REG_SZ, f'"{exe_path}"')
            logger.info("已启用 Windows 开机自启动")
            return True
        elif system == "Darwin":
            plist_dir = Path.home() / "Library" / "LaunchAgents"
            plist_dir.mkdir(parents=True, exist_ok=True)
            plist = plist_dir / "com.meshctx.desktop.plist"
            plist.write_text(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
    <key>Label</key><string>com.meshctx.desktop</string>
    <key>ProgramArguments</key><array><string>{sys.executable}</string><string>{__file__}</string></array>
    <key>RunAtLoad</key><true/>
</dict></plist>""")
            logger.info("已启用 macOS 开机自启动")
            return True
        else:
            autostart_dir = Path.home() / ".config" / "autostart"
            autostart_dir.mkdir(parents=True, exist_ok=True)
            desktop_file = autostart_dir / "meshctx.desktop"
            desktop_file.write_text(f"""[Desktop Entry]
Type=Application
Name=meshctx Desktop
Exec={sys.executable} {__file__}
Terminal=false
X-GNOME-Autostart-enabled=true
""")
            logger.info("已启用 Linux 开机自启动")
            return True
    except Exception as e:
        logger.warning(f"开机自启动设置失败: {e}")
        return False


def disable_autostart():
    """禁用开机自启动"""
    import platform
    system = platform.system()
    try:
        if system == "Windows":
            import winreg
            key = winreg.HKEY_CURRENT_USER
            subkey = r"Software\Microsoft\Windows\CurrentVersion\Run"
            with winreg.OpenKey(key, subkey, 0, winreg.KEY_SET_VALUE) as reg:
                winreg.DeleteValue(reg, "meshctx")
        elif system == "Darwin":
            plist = Path.home() / "Library" / "LaunchAgents" / "com.meshctx.desktop.plist"
            if plist.exists():
                plist.unlink()
        else:
            desktop_file = Path.home() / ".config" / "autostart" / "meshctx.desktop"
            if desktop_file.exists():
                desktop_file.unlink()
        logger.info("已禁用开机自启动")
        return True
    except Exception as e:
        logger.warning(f"禁用自启动失败: {e}")
        return False


def main():
    global PORT
    try:
        logger.info("=" * 50)
        logger.info(f"meshctx Desktop v2.25.0 启动中...")
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

        # 3. 系统托盘 (pystray)
        tray_thread = None
        try:
            from PIL import Image
            import pystray
            
            # 创建托盘图标
            icon_img = Image.new('RGB', (64, 64), color=(88, 101, 242))
            if LOGO_ICO.exists():
                try:
                    icon_img = Image.open(LOGO_ICO)
                    icon_img = icon_img.resize((64, 64), Image.LANCZOS)
                except:
                    pass
            
            def on_open(icon, item):
                import webbrowser
                webbrowser.open(app_url)
            
            def on_quit(icon, item):
                icon.stop()
                os._exit(0)
            
            menu = pystray.Menu(
                pystray.MenuItem("打开 meshctx", on_open, default=True),
                pystray.MenuItem(f"地址: {app_url}", None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", on_quit),
            )
            
            tray_icon = pystray.Icon("meshctx", icon_img, "meshctx Desktop", menu)
            tray_thread = threading.Thread(target=tray_icon.run, daemon=True)
            tray_thread.start()
            logger.info("系统托盘已启动")
        except ImportError:
            logger.info("pystray 未安装，跳过系统托盘")
        except Exception as e:
            logger.warning(f"系统托盘启动失败: {e}")

        # 4. 打开桌面窗口
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
            if tray_thread:
                input("托盘已运行，按 Enter 退出...")
        except Exception as e:
            logger.error(f"窗口启动失败: {traceback.format_exc()}")
            print(f"\n❌ 窗口启动失败: {e}")
            print(f"   请在浏览器打开: {app_url}")
            print(f"   日志: {LOG_FILE}\n")
            import webbrowser
            webbrowser.open(app_url)
            if tray_thread:
                input("托盘已运行，按 Enter 退出...")

    except Exception as e:
        logger.error(f"致命错误: {traceback.format_exc()}")
        print(f"\n❌ 启动失败: {e}\n日志: {LOG_FILE}\n")
        input("按 Enter 退出...")


if __name__ == "__main__":
    main()
