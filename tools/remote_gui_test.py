#!/usr/bin/env python3
"""
远程Windows GUI自动化测试 — 通过meshctx HTTP API控制192.168.3.47
1. 上传安装器到目标机
2. 执行GUI自动化安装
3. 截图验证7语言选择页
"""
import urllib.request
import json
import time
import sys
import os

TARGET = "http://192.168.3.47:3001"
INSTALLER_PATH = "/mnt/e/Meshctx/dist/meshctx-setup.exe"

def remote(cmd, timeout=60):
    """通过meshctx终端API执行远程命令"""
    try:
        data = json.dumps({"cmd": cmd}).encode()
        req = urllib.request.Request(f"{TARGET}/api/terminal", data=data,
            headers={"Content-Type": "application/json"}, method="POST")
        resp = urllib.request.urlopen(req, timeout=timeout)
        result = json.loads(resp.read())
        return result
    except Exception as e:
        return {"output": "", "error": str(e), "exit_code": -1}

def upload_file():
    """上传安装器到目标机"""
    print("=== Step 1: Upload installer ===")
    
    # Read installer
    with open(INSTALLER_PATH, "rb") as f:
        data = f.read()
    print(f"  Installer: {len(data)/1024/1024:.1f}MB")
    
    # Encode as base64
    import base64
    encoded = base64.b64encode(data).decode()
    
    # Split into chunks (API has size limits)
    chunk_size = 50000
    chunks = [encoded[i:i+chunk_size] for i in range(0, len(encoded), chunk_size)]
    print(f"  Chunks: {len(chunks)}")
    
    # Send chunks to target
    remote("mkdir C:\\MeshCtxTest 2>nul & echo OK", 10)
    
    for i, chunk in enumerate(chunks):
        cmd = f'powershell -Command "Add-Content -Path C:\\MeshCtxTest\\setup.b64 -Value \'{chunk}\' -NoNewline" 2>&1'
        result = remote(cmd, 30)
        if i % 10 == 0:
            print(f"  Chunk {i+1}/{len(chunks)}...")
    
    # Decode
    print("  Decoding...")
    result = remote(
        'powershell -Command "$b64=Get-Content C:\\MeshCtxTest\\setup.b64 -Raw; [IO.File]::WriteAllBytes(\'C:\\MeshCtxTest\\setup.exe\',[Convert]::FromBase64String($b64)); Write-Host DONE"',
        120
    )
    print(f"  Decode: {result.get('output','')[:100]}")
    
    # Verify
    result = remote("powershell -Command \"(Get-Item C:\\MeshCtxTest\\setup.exe).Length\"", 10)
    size = result.get("output", "?").strip()
    print(f"  File size: {size} bytes")

def gui_test():
    """GUI自动化安装测试"""
    print("\n=== Step 2: GUI Install Test ===")
    
    # Launch installer
    print("  Launching installer...")
    remote("start C:\\MeshCtxTest\\setup.exe", 10)
    time.sleep(5)
    
    # Screenshot 1: Language page
    print("  Screenshot: language page")
    result = remote(
        'powershell -Command "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; $b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds; $bmp=New-Object System.Drawing.Bitmap($b.Width,$b.Height); $g=[System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($b.X,$b.Y,0,0,$b.Size); $g.Dispose(); $bmp.Save(\'C:\\MeshCtxTest\\screenshot_lang.png\',[System.Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose(); Write-Host DONE"',
        30
    )
    print(f"  Result: {result.get('output','')[:50]}")
    
    # Send Enter to proceed (English default)
    remote(
        'powershell -Command "[System.Windows.Forms.SendKeys]::SendWait(\'{ENTER}\')"',
        5
    )
    time.sleep(2)
    
    # Screenshot 2: Welcome page
    remote(
        'powershell -Command "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; $b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds; $bmp=New-Object System.Drawing.Bitmap($b.Width,$b.Height); $g=[System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($b.X,$b.Y,0,0,$b.Size); $g.Dispose(); $bmp.Save(\'C:\\MeshCtxTest\\screenshot_welcome.png\'); $bmp.Dispose(); Write-Host DONE"',
        20
    )
    
    # Navigate through installer
    remote('powershell -Command "[System.Windows.Forms.SendKeys]::SendWait(\'{ENTER}\')"', 5)
    time.sleep(2)
    remote('powershell -Command "[System.Windows.Forms.SendKeys]::SendWait(\'C:\\\\MeshCtxTest{ENTER}\')"', 5)
    
    time.sleep(8)
    
    # Screenshot 3: Finish
    remote(
        'powershell -Command "Add-Type -AssemblyName System.Windows.Forms,System.Drawing; $b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds; $bmp=New-Object System.Drawing.Bitmap($b.Width,$b.Height); $g=[System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($b.X,$b.Y,0,0,$b.Size); $g.Dispose(); $bmp.Save(\'C:\\MeshCtxTest\\screenshot_finish.png\'); $bmp.Dispose(); Write-Host DONE"',
        20
    )
    
    print("  Screenshots saved!")
    
    # List results
    result = remote("dir C:\\MeshCtxTest\\screenshot_*.png", 10)
    print(f"  Files: {result.get('output','')[:200]}")

def run():
    upload_file()
    gui_test()
    
    # Verify installation
    print("\n=== Step 3: Verify ===")
    result = remote("dir C:\\MeshCtxTest\\meshctx-desktop.exe 2>nul && echo INSTALL_OK || echo INSTALL_FAIL", 10)
    print(f"  Install: {result.get('output','')[:100]}")
    
    result = remote("powershell -Command \"(Get-Item C:\\MeshCtxTest\\meshctx-desktop.exe -ErrorAction SilentlyContinue).VersionInfo.FileVersion\"", 10)
    print(f"  Version: {result.get('output','')[:50]}")

if __name__ == "__main__":
    run()
