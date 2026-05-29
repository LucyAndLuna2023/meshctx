"""Try raw NTLM auth via requests + access WinRM endpoint"""
import requests
from requests_ntlm import HttpNtlmAuth
import base64

HOST = "bore.pub"
PORT = 33254

# Method 1: requests-ntlm direct
print("=== Method 1: requests-ntlm ===")
try:
    # First just test if the endpoint responds
    r = requests.get(f"http://{HOST}:{PORT}/wsman", timeout=10)
    print(f"GET /wsman: {r.status_code}")
    print(f"Headers: {dict(r.headers)}")
    print(f"Body[:200]: {r.text[:200]}")
except Exception as e:
    print(f"GET failed: {e}")

# Method 2: Try with pre-authentication
print("\n=== Method 2: NTLM auth ===")
try:
    auth = HttpNtlmAuth('Administrator', '')
    r = requests.post(
        f"http://{HOST}:{PORT}/wsman",
        auth=auth,
        data='',
        headers={'Content-Type': 'application/soap+xml;charset=UTF-8'},
        timeout=10
    )
    print(f"POST /wsman: {r.status_code}")
except Exception as e:
    print(f"NTLM POST failed: {e}")

# Method 3: Try SMB port
print("\n=== Method 3: Try exposing port 445 ===")
import socket
s = socket.socket()
s.settimeout(5)
try:
    s.connect((HOST, PORT))
    # Send SMB negotiate
    s.send(b'\x00\x00\x00\xa4\xff\x53\x4d\x42\x72\x00\x00\x00\x00\x18\x01\x48\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xfe\xff\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00')
    resp = s.recv(1024)
    print(f"SMB response: {len(resp)} bytes, first: {resp[:20].hex()}")
    s.close()
except Exception as e:
    print(f"SMB: {e}")

# Method 4: Try WMI/DCOM port 135
print("\n=== Method 4: DCOM/RPC ===")
try:
    import socket
    s = socket.socket()
    s.settimeout(5)
    s.connect((HOST, PORT))
    # RPC bind
    rpc_bind = bytes.fromhex('05 00 0b 03 10 00 00 00 48 00 00 00 01 00 00 00'.replace(' ',''))
    s.send(rpc_bind)
    resp = s.recv(1024)
    print(f"RPC response: {len(resp)} bytes")
    s.close()
except Exception as e:
    print(f"RPC: {e}")
