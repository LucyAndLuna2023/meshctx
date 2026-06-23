"""Connect to 192.168.3.47 via bore tunnel"""
import sys
import traceback

BORE_HOST = "bore.pub"
BORE_PORT = 33254
TARGET_USER = "Administrator"
TARGET_PASS = ""

try:
    from winrm.protocol import Protocol
    
    p = Protocol(
        endpoint=f'http://{BORE_HOST}:{BORE_PORT}/wsman',
        transport='ntlm',
        username=TARGET_USER,
        password=TARGET_PASS,
    )
    
    shell_id = p.open_shell()
    print(f"SHELL_OPENED: {shell_id}")
    
    # Test 1: hostname
    cmd_id = p.run_command(shell_id, 'hostname')
    stdout, stderr, exit_code = p.get_command_output(shell_id, cmd_id)
    p.cleanup_command(shell_id, cmd_id)
    hostname = stdout.decode().strip()
    print(f"HOSTNAME: {hostname}")
    
    # Test 2: WSL
    cmd_id2 = p.run_command(shell_id, 'wsl hostname')
    out2, err2, ec2 = p.get_command_output(shell_id, cmd_id2)
    p.cleanup_command(shell_id, cmd_id2)
    print(f"WSL: {out2.decode().strip()} (exit={ec2})")
    
    # Test 3: Python version
    cmd_id3 = p.run_command(shell_id, 'python --version 2>&1')
    out3, err3, ec3 = p.get_command_output(shell_id, cmd_id3)
    p.cleanup_command(shell_id, cmd_id3)
    print(f"PYTHON: {out3.decode().strip()}")
    
    # Test 4: Directory listing
    cmd_id4 = p.run_command(shell_id, 'dir C:\\ 2>&1')
    out4, err4, ec4 = p.get_command_output(shell_id, cmd_id4)
    p.cleanup_command(shell_id, cmd_id4)
    print(f"C:\\: {out4.decode().strip()[:200]}")
    
    p.close_shell(shell_id)
    print("\n=== CONNECTION SUCCESSFUL ===")
    
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")
    traceback.print_exc()
    sys.exit(1)
