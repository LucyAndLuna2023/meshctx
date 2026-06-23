"""Setup build environment on 192.168.3.47"""
from winrm.protocol import Protocol
p=Protocol(endpoint='http://bore.pub:32306/wsman',transport='ntlm',username='Administrator',password='')
p.transport.read_timeout_sec=180; p.transport.operation_timeout_sec=160

def run(cmd):
    s=p.open_shell(); c=p.run_command(s,cmd)
    o,e,ec=p.get_command_output(s,c); p.cleanup_command(s,c); p.close_shell(s)
    return o.decode(errors='replace')

# 1. Install NSIS via chocolatey or direct download
print("=== Installing NSIS ===")
# Try chocolatey first
o=run('powershell -Command "choco install nsis -y --limit-output" 2>&1')
print(o[:300])

# 2. Install PyInstaller
print("\n=== Installing PyInstaller ===")
o=run('pip install pyinstaller -q 2>&1')
print(o[:300])

# 3. Clone meshctx to Windows
print("\n=== Cloning meshctx ===")
o=run('git clone https://github.com/LucyAndLuna2023/meshctx.git C:\\meshctx 2>&1 || echo already exists')
print(o[:300])

# 4. Install deps
print("\n=== Installing deps ===")
o=run('cd /d C:\\meshctx && pip install fastapi uvicorn pydantic httpx jinja2 pyyaml requests python-multipart numpy aiofiles -q 2>&1')
print(o[:300])

# 5. Verify
print("\n=== Verify ===")
o=run('makensis /VERSION 2>&1 & python -c "import PyInstaller; print(\'PyInstaller OK\')" 2>&1')
print(o[:300])

print("\n=== DONE ===")
