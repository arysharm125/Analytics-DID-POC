
import sys
import os

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from app.services.audit_core import ServerAuditEngine

def test_audit_engine_loading():
    try:
        engine = ServerAuditEngine()
        print("ServerAuditEngine initialized successfully.")
        
        script_content = engine.network_audit_script_content
        if "def get_nic_data():" in script_content and "class colors:" in script_content:
            print("SUCCESS: Network audit script loaded correctly.")
            print(f"Script length: {len(script_content)} characters")
        else:
            print("FAILURE: Network audit script content does not match expected content.")
            print(f"Content snippet: {script_content[:100]}...")
            
    except Exception as e:
        print(f"FAILURE: Exception during initialization: {e}")

if __name__ == "__main__":
    test_audit_engine_loading()
