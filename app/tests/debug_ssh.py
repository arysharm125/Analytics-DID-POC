
import subprocess
import sys

def test_ssh_command(host, user, password):
    print(f"Testing SSH connection to {user}@{host}...")
    
    # Simple command to check connectivity and sudo
    remote_command_block = f"""
    echo "{password}" | sudo -S -p "" echo "Sudo access confirmed"
    """
    
    local_command = [
        "sshpass", "-p", password,
        "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
        f"{user}@{host}", remote_command_block
    ]
    
    print(f"Executing command: {' '.join(local_command)}")
    
    try:
        # TIMEOUT increased to match what we put in the main code
        result = subprocess.run(local_command, capture_output=True, text=True, check=False, timeout=30)
        
        print(f"\n--- Return Code: {result.returncode} ---")
        print(f"\n--- STDOUT ---\n{result.stdout}")
        print(f"\n--- STDERR ---\n{result.stderr}")
        
        if result.returncode == 0:
            print("\nSUCCESS: SSH connection and sudo check passed.")
        else:
            print("\nFAILURE: SSH command failed.")
            
    except Exception as e:
        print(f"\nEXCEPTION: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("Usage: python3 debug_ssh.py <host> <user> <password>")
        sys.exit(1)
        
    test_ssh_command(sys.argv[1], sys.argv[2], sys.argv[3])
