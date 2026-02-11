import sys
import os

# Add the project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))

from app.services.audit_core import ServerAuditEngine

def test_audit_engine_structure():
    try:
        engine = ServerAuditEngine()
        print("ServerAuditEngine initialized successfully.")
        
        # Check method existence
        if not hasattr(engine, '_map_profile_to_metadata'):
            print("FAILURE: _map_profile_to_metadata method NOT found in engine instance.")
            return
        
        if not hasattr(engine, '_generate_reports'):
            print("FAILURE: _generate_reports method NOT found in engine instance.")
            return

        print("SUCCESS: Methods found.")
        
        # Try a dummy call to _map_profile_to_metadata
        try:
            profile = {
                "SystemInfo": {"Model": "Test CPU"},
                "BiosSettings": {"Test": "Value"}
            }
            res = engine._map_profile_to_metadata(profile)
            print(f"Call successful. Result: {res}")
        except Exception as e:
            print(f"FAILURE: Call to _map_profile_to_metadata raised exception: {e}")

    except Exception as e:
        print(f"FAILURE: Exception during initialization: {e}")

if __name__ == "__main__":
    test_audit_engine_structure()
