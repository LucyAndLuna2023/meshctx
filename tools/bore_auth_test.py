"""Test multiple auth methods through bore tunnel"""
import sys
from winrm.protocol import Protocol

HOST = "bore.pub"
PORT = 33254

# Try different transports and auth formats
tests = [
    ("ntlm", "Administrator", ""),
    ("ntlm", ".\\Administrator", ""),
    ("ntlm", "Administrator", "admin"),
    ("basic", "Administrator", ""),
    ("basic", "Administrator", "password"),
    ("credssp", "Administrator", ""),
]

for transport, user, pw in tests:
    try:
        p = Protocol(
            endpoint=f'http://{HOST}:{PORT}/wsman',
            transport=transport,
            username=user,
            password=pw,
        )
        shell_id = p.open_shell()
        cmd_id = p.run_command(shell_id, 'echo OK')
        stdout, stderr, ec = p.get_command_output(shell_id, cmd_id)
        p.cleanup_command(shell_id, cmd_id)
        p.close_shell(shell_id)
        print(f"✓ {transport} {user}/{pw if pw else '(empty)'}: OK")
        sys.exit(0)
    except Exception as e:
        errmsg = str(e)[:60]
        print(f"✗ {transport} {user}/{pw if pw else '(empty)'}: {errmsg}")

# Try HTTPS
print("\n=== Trying HTTPS ===")
try:
    p = Protocol(
        endpoint=f'https://{HOST}:{PORT}/wsman',
        transport='ntlm',
        username='Administrator',
        password='',
        server_cert_validation='ignore',
    )
    shell_id = p.open_shell()
    print("HTTPS OK!")
except Exception as e:
    print(f"HTTPS: {type(e).__name__}: {e}")
