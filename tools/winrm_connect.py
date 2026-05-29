"""Direct pywinrm connection to 192.168.3.47"""
import sys
import traceback

try:
    from winrm.protocol import Protocol
    
    print("=== Attempt 1: Basic auth port 5985 ===")
    p = Protocol(
        endpoint='http://192.168.3.47:5985/wsman',
        transport='ntlm',
        username='Administrator',
        password='',
    )
    shell_id = p.open_shell()
    command_id = p.run_command(shell_id, 'hostname')
    stdout, stderr, exit_code = p.get_command_output(shell_id, command_id)
    p.cleanup_command(shell_id, command_id)
    p.close_shell(shell_id)
    print(f"OK! hostname={stdout.decode().strip()}, exit={exit_code}")
    
    # Test WSL on target
    shell_id2 = p.open_shell()
    cmd_id2 = p.run_command(shell_id2, 'wsl hostname 2>&1')
    out2, err2, ec2 = p.get_command_output(shell_id2, cmd_id2)
    p.cleanup_command(shell_id2, cmd_id2)
    p.close_shell(shell_id2)
    print(f"WSL: {out2.decode().strip()} (exit={ec2})")
    
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")
    
    # Try port 5998
    try:
        print("\n=== Attempt 2: Port 5998 ===")
        from winrm.protocol import Protocol
        p = Protocol(
            endpoint='http://192.168.3.47:5998/wsman',
            transport='ntlm',
            username='Administrator',
            password='',
        )
        shell_id = p.open_shell()
        command_id = p.run_command(shell_id, 'hostname')
        stdout, stderr, exit_code = p.get_command_output(shell_id, command_id)
        print(f"OK! hostname={stdout.decode().strip()}")
    except Exception as e2:
        print(f"5998 FAIL: {type(e2).__name__}: {e2}")
        
        # Try basic auth
        try:
            print("\n=== Attempt 3: basic auth ===")
            p = Protocol(
                endpoint='http://192.168.3.47:5985/wsman',
                transport='basic',
                username='Administrator',
                password='',
            )
            shell_id = p.open_shell()
            print(f"basic auth OK: shell={shell_id}")
        except Exception as e3:
            print(f"basic FAIL: {type(e3).__name__}: {e3}")
