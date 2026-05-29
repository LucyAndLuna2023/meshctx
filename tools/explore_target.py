"""Full system exploration of 192.168.3.47"""
from winrm.protocol import Protocol

p = Protocol(
    endpoint='http://bore.pub:32306/wsman',
    transport='ntlm',
    username='Administrator',
    password='',
)
p.transport.read_timeout_sec = 30
p.transport.operation_timeout_sec = 20

def run(cmd):
    s = p.open_shell()
    c = p.run_command(s, cmd)
    o, e, ec = p.get_command_output(s, c)
    p.cleanup_command(s, c)
    p.close_shell(s)
    return o.decode(errors='replace').strip(), e.decode(errors='replace').strip(), ec

# System info
print("=== SYSTEM ===")
o, e, ec = run('systeminfo | findstr /C:"OS Name" /C:"System Type" /C:"Total Physical Memory" /C:"Available Physical Memory"')
print(o)

# WSL
print("\n=== WSL ===")
o, e, ec = run('wsl --status 2>&1')
print(o)

o2, e2, ec2 = run('wsl hostname 2>&1')
print(f"WSL hostname: {o2.strip()}")

# Python versions
print("\n=== PYTHON ===")
for py in ['python --version', 'python3 --version', 'where python']:
    o, e, ec = run(py)
    print(f"  {py}: {o.strip() or e.strip()}")

# Disk
print("\n=== DISK ===")
o, e, ec = run('wmic logicaldisk get size,freespace,caption 2>&1')
print(o)

# Network
print("\n=== NETWORK ===")
o, e, ec = run('ipconfig | findstr /C:"IPv4" /C:"192.168"')
print(o)

print("\n=== DONE ===")
