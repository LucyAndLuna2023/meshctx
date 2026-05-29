"""Test WinRM connectivity to 192.168.3.47"""
import sys
import traceback

# Try multiple approaches
print("=== Attempt 1: pywinrm direct ===")
try:
    import winrm
    s = winrm.Session('192.168.3.47', auth=('Administrator', ''), transport='ntlm')
    r = s.run_cmd('hostname')
    print(f"OK: {r.std_out.decode().strip()}")
    sys.exit(0)
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")

print("\n=== Attempt 2: pywinrm with basic auth ===")
try:
    import winrm
    s = winrm.Session('192.168.3.47', auth=('Administrator', ''), transport='basic')
    r = s.run_cmd('hostname')
    print(f"OK: {r.std_out.decode().strip()}")
    sys.exit(0)
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")

print("\n=== Attempt 3: requests to WinRM HTTP ===")
try:
    import requests
    from requests.auth import HTTPBasicAuth
    r = requests.get('http://192.168.3.47:5985/wsman', auth=HTTPBasicAuth('Administrator', ''), timeout=10)
    print(f"HTTP {r.status_code}: {r.text[:200]}")
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")

print("\n=== Attempt 4: TCP socket ===")
try:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    result = s.connect_ex(('192.168.3.47', 5998))
    s.close()
    print(f"Port 5998: {'OPEN' if result == 0 else 'CLOSED'} (code={result})")
except Exception as e:
    print(f"FAIL: {e}")

print("\n=== Attempt 5: Various ports ===")
for port in [22, 445, 135, 5985, 5986, 5998, 3389]:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(3)
        result = s.connect_ex(('192.168.3.47', port))
        s.close()
        status = "OPEN" if result == 0 else "closed"
        print(f"  Port {port}: {status}")
    except:
        print(f"  Port {port}: error")
