import urllib.request, os, time, json, sys

TARGET = "http://192.168.3.47:3001"

def remote(cmd, timeout=120):
    data = json.dumps({"cmd": cmd}).encode()
    req = urllib.request.Request(f"{TARGET}/api/terminal", data=data,
        headers={"Content-Type": "application/json"}, method="POST")
    resp = urllib.request.urlopen(req, timeout=timeout)
    return json.loads(resp.read())

# Step 1: Download via meshctx's Python
print("1. Download...")
dl = "import urllib.request,os;os.makedirs('C:/MeshCtxGUITest',exist_ok=True);urllib.request.urlretrieve('http://192.168.3.45:8889/meshctx-setup.exe','C:/MeshCtxGUITest/setup.exe');print('OK',os.path.getsize('C:/MeshCtxGUITest/setup.exe')//1048576,'MB')"
r = remote(f'python -c "{dl}"', 120)
print(f"  {r.get('output','')} {r.get('error','')[:100]}")

# Step 2: Verify
print("2. Verify...")
r = remote('powershell -Command "$f=Get-Item C:\\MeshCtxGUITest\\setup.exe -EA SilentlyContinue;if($f){Write-Host (\\\"OK \\\"+[math]::Round($f.Length/1MB,1)+\\\"MB\\\")}else{Write-Host NOT_FOUND}"', 15)
print(f"  {r.get('output','')}")

# Step 3: GUI test - launch installer + screenshot each language
if "OK" in str(r.get('output','')):
    print("3. GUI test - launching installer...")
    r = remote('start C:\\MeshCtxGUITest\\setup.exe', 10)
    time.sleep(5)
    
    print("4. Screenshot language page...")
    scr = 'powershell -Command "Add-Type -AssemblyName System.Windows.Forms,System.Drawing;$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;$bmp=New-Object System.Drawing.Bitmap($b.Width,$b.Height);$g=[System.Drawing.Graphics]::FromImage($bmp);$g.CopyFromScreen($b.X,$b.Y,0,0,$b.Size);$g.Dispose();$bmp.Save(\\\"C:\\MeshCtxGUITest\\scr_lang.png\\\");$bmp.Dispose();Write-Host OK"'
    r = remote(scr, 20)
    print(f"  {r.get('output','')[:100]}")
    
    print("5. Done!")
    r = remote('dir C:\\MeshCtxGUITest\\*.png', 10)
    print(f"  {r.get('output','')[:200]}")
else:
    print("FAIL - installer not found")
