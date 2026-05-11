"""
meshctx Windows 启动入口
双击 .exe → 启动服务 → 打开窗口/浏览器
"""
import os, sys, time, threading, subprocess
from src.main import app  # Ensure PyInstaller detects this

def open_browser():
    url = "http://127.0.0.1:3000/ui/chat"
    try:
        if sys.platform == "win32":
            os.startfile(url)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", url])
        else:
            subprocess.Popen(["xdg-open", url])
    except:
        pass

def start_backend():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=3000, log_level="warning")

if __name__ == "__main__":
    print("meshctx v1.1 — Starting...")
    
    # 启动后端
    server = threading.Thread(target=start_backend, daemon=True)
    server.start()
    
    # 等服务器就绪
    time.sleep(2)
    
    # 打开GUI
    try:
        import webview
        webview.create_window(
            "meshctx v1.1 — Self-Evolving Agent",
            "http://127.0.0.1:3000/ui/chat",
            width=1200, height=800,
            min_size=(800, 600),
        )
        webview.start()
    except ImportError:
        # 回退: 打开系统浏览器
        print("Opening http://127.0.0.1:3000/ui/chat ...")
        open_browser()
        print("Press Ctrl+C to stop")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("Shutting down...")
