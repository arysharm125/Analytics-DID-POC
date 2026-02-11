# app/tests/test_audit_profiler.py
import unittest
from unittest.mock import patch, MagicMock, mock_open
import os
import sys

# Add the project root to sys.path
# Go up 3 levels: app/tests/ -> app/ -> / (root)
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.services.audit_core import ServerAuditEngine

class TestAuditProfiler(unittest.TestCase):
    def setUp(self):
        # We need to patch _load_json_file BEFORE instantiating ServerAuditEngine
        # because __init__ calls it.
        self.patcher = patch.object(ServerAuditEngine, '_load_json_file')
        self.mock_load_json = self.patcher.start()
        self.mock_load_json.return_value = {} # Default empty dict for resources
        
        self.engine = ServerAuditEngine()
        self.test_host = "10.86.27.69"
        self.test_user = "amd"
        self.test_password = "password"

    def tearDown(self):
        self.patcher.stop()

    @patch("app.services.audit_core.subprocess.run")
    def test_execute_platform_profiler(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="OK")
        
        self.engine._execute_platform_profiler(self.test_host, self.test_user, self.test_password)
        
        mock_run.assert_called_with(
            ["/home/ubuntu/platform-profiler", "--osip", self.test_host, "--osuser", self.test_user, "--ospwd", self.test_password],
            capture_output=True, text=True, check=True, timeout=300
        )

    @patch("app.services.audit_core.glob.glob")
    @patch("app.services.audit_core.os.path.getmtime")
    @patch("app.services.audit_core.os.path.exists")
    @patch("app.services.audit_core.ServerAuditEngine._generate_reports")
    def test_run_full_audit_flow(self, mock_generate_reports, mock_exists, mock_mtime, mock_glob):
        # Mock glob to return a directory
        fake_dir = "/tmp/PlatformProfile_10_86_27_69_100"
        mock_glob.return_value = [fake_dir]
        mock_mtime.return_value = 100
        mock_exists.return_value = True
        
        # Mock the profile data loading
        fake_profile = {
            "SystemInfo": {
                "Model": "EPYC 9654",
                "Turbo": "Enabled",
                "ThreadsPerCore": 2
            },
            "BiosSettings": {
                "SMT Control": "Auto"
            },
            "OsInfo": {
                "KernelParams": "console=ttyS0"
            }
        }
        
        # Mock _execute_platform_profiler (we can just mock the method on the instance to skip subprocess)
        self.engine._execute_platform_profiler = MagicMock()
        
        # Configure mock_load_json to return fake_profile
        def load_json_side_effect(path, desc):
            if "PlatformProfile.json" in path:
                return fake_profile
            return {}
        self.mock_load_json.side_effect = load_json_side_effect
        
        # Mock generate reports to return a dummy report
        expected_report = {"summary": "PASS"}
        mock_generate_reports.return_value = expected_report
        
        # Execute
        result = self.engine.run_full_audit(self.test_host, self.test_user, self.test_password, "SPECCPU")
        
        # Verify
        self.engine._execute_platform_profiler.assert_called_once()
        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(result["config_report"], expected_report)
        
        # Verify mapping logic implicitly by checking what _generate_reports was called with
        args, _ = mock_generate_reports.call_args
        benchmark_name, server_metadata, verification_data = args
        
        self.assertEqual(verification_data["Data"]["verification_details"]["sut"]["model"], "EPYC 9654")
        self.assertEqual(verification_data["Data"]["turbo_status"], "Enabled")
        self.assertEqual(server_metadata["Data"]["bios_settings"]["SMT Control"], "Auto")
        self.assertIn('GRUB_CMDLINE_LINUX_DEFAULT="console=ttyS0"', server_metadata["Data"]["fileTunings"][0])

if __name__ == "__main__":
    unittest.main()


if __name__ == "__main__":
    unittest.main()
