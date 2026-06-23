#!/usr/bin/env python3
"""Enable WinRM on 192.168.3.47 then run GUI test"""
import urllib.request, json, time, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def remote(cmd, timeout=30):
    data = json.dumps({"cmd": cmd}).encode()
    req = urllib.request.Request("http://192.168.3.47:3001/api/terminal",
        data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
        return json.loads(resp.read())
    except Exception as e:
        return {"output":"","error":str(e)[:100],"exit_code":-1}

print("=== Enable WinRM on 192.168.3.47 ===")

# Step 1: Enable PSRemoting
print("1. Enable-PSRemoting...")
r = remote("powershell -Command \"Enable-PSRemoting -Force -SkipNetworkProfileCheck 2>&1\"", 20)
out = r.get('output','') + r.get('error','')
print(f"   {out[:150]}")

# Step 2: Start WinRM service
print("2. Start WinRM...")
r = remote("sc config WinRM start=auto 2>&1", 10)
r = remote("net start WinRM 2>&1", 10)
out = r.get('output','') + r.get('error','')
print(f"   {out[:100]}")

# Step 3: Allow blank password
print("3. Allow blank password...")
r = remote("reg add \"HKLM\\SYSTEM\\CurrentControlSet\\Control\\Lsa\" /v LimitBlankPasswordUse /t REG_DWORD /d 0 /f 2>&1", 10)
print(f"   {r.get('output','')[:100]}")

# Step 4: Disable firewall
print("4. Disable firewall...")
r = remote("netsh advfirewall set allprofiles state off 2>&1", 10)
print(f"   {r.get('output','')[:100]}")

time.sleep(3)

# Step 5: Test WinRM from Windows host
print("5. Test WinRM...")
# Use PowerShell from this WSL to test via Windows host
import subprocess
ps_cmd = '''powershell -Command "
try {
    $cred = New-Object PSCredential('Administrator',(ConvertTo-SecureString '' -AsPlainText -Force))
    $s = New-PSSession -ComputerName 192.168.3.47 -Credential $cred -Authentication Negotiate -ErrorAction Stop
    Write-Host 'WINRM_CONNECTED'
    $r = Invoke-Command -Session $s -ScriptBlock { hostname }
    Write-Host $r
    Remove-PSSession $s
} catch { Write-Host ('FAIL:' + $_.Exception.Message.Substring(0,120)) }
"'''
result = subprocess.run(ps_cmd, shell=True, capture_output=True, text=True, timeout=20)
print(f"   {result.stdout[:200]}")
