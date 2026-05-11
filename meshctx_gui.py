"""
meshctx Windows GUI — 原生桌面窗口
双击 .exe → 弹出窗口 → 输入Key → 开始使用
"""
import sys
import os
import json
import threading
import webbrowser

# 后台启动服务
def start_server():
    import uvicorn
    from src.main import app as fastapi_app
    uvicorn.run(fastapi_app, host="127.0.0.1", port=3000, log_level="warning")

# 启动服务线程
server_thread = threading.Thread(target=start_server, daemon=True)
server_thread.start()

# 尝试使用 WebView2 (Windows 原生)
HAS_GUI = False
try:
    import webview
    import time
    time.sleep(2)  # 等服务器就绪
    webview.create_window(
        "meshctx v1.1 — Self-Evolving Agent",
        "http://127.0.0.1:3000/ui/chat",
        width=1200, height=800,
        min_size=(800, 600),
    )
    webview.start()
    HAS_GUI = True
except ImportError:
    pass

# 回退: PyQt5
if not HAS_GUI:
    try:
        from PyQt5.QtWidgets import QApplication, QMainWindow
        from PyQt5.QtWebEngineWidgets import QWebEngineView
        from PyQt5.QtCore import QUrl
        import time
        time.sleep(2)
        app = QApplication(sys.argv)
        window = QMainWindow()
        window.setWindowTitle("meshctx v1.1 — Self-Evolving Agent")
        window.resize(1200, 800)
        web = QWebEngineView()
        web.setUrl(QUrl("http://127.0.0.1:3000/ui/chat"))
        window.setCentralWidget(web)
        window.show()
        app.exec_()
        HAS_GUI = True
    except ImportError:
        pass

# 最后回退: 打开浏览器
if not HAS_GUI:
    print("Starting meshctx...")
    print("Opening http://127.0.0.1:3000/ui/chat in your browser")
    webbrowser.open("http://127.0.0.1:3000/ui/chat")
    # Keep running
    try:
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        pass
