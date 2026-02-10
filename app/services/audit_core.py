# app/services/audit_core.py
import os
import json
import subprocess
import time
import sys
import re
import shlex
import socket
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger("audit_core")

# Constants for paths relative to this file
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESOURCES_DIR = os.path.join(BASE_DIR, "resources")

class ServerAuditEngine:
    def __init__(self, 
                 tuning_guide_file: str = "AMD_EPYC_Series_BIOS_Tuning_Guide.json",
                 benchmark_map_file: str = "benchmark_tuning_map.json",
                 compatibility_map_file: str = "profile_compatibility_map.json",
                 network_audit_script_file: str = "network_audit.py"):
        
        # Auto-resolve paths to app/resources/
        self.tuning_guide_path = os.path.join(RESOURCES_DIR, tuning_guide_file)
        self.benchmark_map_path = os.path.join(RESOURCES_DIR, benchmark_map_file)
        self.compatibility_map_path = os.path.join(RESOURCES_DIR, compatibility_map_file)
        self.network_audit_script_path = os.path.join(RESOURCES_DIR, network_audit_script_file)
        
        # Load resources
        self.tuning_guide = self._load_json_file(self.tuning_guide_path, "Tuning Guide")
        self.benchmark_map = self._load_json_file(self.benchmark_map_path, "Benchmark Map")
        self.compatibility_map = self._load_json_file(self.compatibility_map_path, "Compatibility Map")
        
        # Load Network Audit Script
        self.network_audit_script_content = self._load_text_file(self.network_audit_script_path, "Network Audit Script")
        
        # Normalize keys
        raw_map = self.benchmark_map.get("benchmark_tuning_map", {})
        self.normalized_benchmark_map = {k.upper(): v for k, v in raw_map.items()}

        # Use Env Var for API URL
        self.api_base_url = os.getenv("DEAE_API_URL", "http://deae-ui-dev.amd.com:8080/benchmarkapi/v1")

    def _load_json_file(self, file_path: str, file_desc: str) -> Dict[str, Any]:
        try:
            with open(file_path, 'r') as f:
                return json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"{file_desc} file not found at: '{file_path}'")
        except json.JSONDecodeError as e:
            raise json.JSONDecodeError(f"Invalid JSON in '{file_desc}' file: {e}", doc=e.doc, pos=e.pos)

    def _load_text_file(self, file_path: str, file_desc: str) -> str:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            raise FileNotFoundError(f"{file_desc} file not found at: '{file_path}'")
        except Exception as e:
            raise RuntimeError(f"Failed to read '{file_desc}' file: {e}")

    def _execute_curl_command(self, curl_cmd_list: list, cmd_description: str) -> Optional[str]:
        try:
            result = subprocess.run(curl_cmd_list, capture_output=True, text=True, check=True, timeout=5)
            return result.stdout
        except subprocess.CalledProcessError as e:
            logger.error(f"{cmd_description} failed: {e.stderr.strip()}")
        except Exception as e:
            logger.error(f"Unexpected curl failure: {e}")
        return None

    def _verify_resources(self, host, username, password):
        api_url = f"{self.api_base_url}/verifyresources"
        payload = {"sut": {"host": host, "username": username, "password": password, "protocol": "ssh"}}
        cmd = ["curl", "-L", api_url, "-H", "Content-Type: application/json", "--data", json.dumps(payload), "-s"]
        text = self._execute_curl_command(cmd, "Verify Resources")
        return json.loads(text) if text else None

    def _get_combined_metadata(self, host, username, password):
        api_url = f"{self.api_base_url}/resource/getcombinedmetadata"
        payload = {"host": host, "username": username, "password": password, "protocol": "ssh"}
        cmd = ["curl", "-L", api_url, "-H", "Content-Type: application/json", "--data", json.dumps(payload), "-s"]
        text = self._execute_curl_command(cmd, "Get Combined Metadata")
        return json.loads(text) if text else None

    def _execute_network_audit_remotely(self, host: str, user: str, password: str) -> Dict[str, str]:
        script_path = f"/tmp/network_evaluator_{int(time.time())}.py"

        # --- UPDATED BASH SCRIPT WITH AUTO-INSTALLATION ---
        remote_command_block = f"""
set -e
SCRIPT_PATH="{script_path}"

# 1. Create the Python script
cat << 'EOF' > $SCRIPT_PATH
{self.network_audit_script_content}
EOF

chmod +x $SCRIPT_PATH

        # 2. Execute with SUDO: Run Script
        # We pipe the password to sudo. 
        echo "{password}" | sudo -S -p "" python3 $SCRIPT_PATH
        
        # 3. Cleanup
        rm -f $SCRIPT_PATH
        """
        local_command = [
            "sshpass", "-p", password,
            "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
            f"{user}@{host}", remote_command_block
        ]

        try:
            result = subprocess.run(local_command, capture_output=True, text=True, check=False, timeout=600)
            if result.returncode != 0:
                logger.error(f"SSH command returned {result.returncode}")
            return {"stdout": result.stdout, "stderr": result.stderr}

        except FileNotFoundError:
            raise EnvironmentError("`sshpass` not installed locally.")
        except subprocess.TimeoutExpired:
            raise TimeoutError("SSH connection or script execution timed out.")
        except Exception as e:
            raise ConnectionError(f"Unexpected SSH error: {e}")

    def _generate_reports(self, benchmark_name: str, server_metadata: Dict[str, Any], verification_data: Dict[str, Any]) -> Dict[str, Any]:
        ver_data = verification_data.get("Data") or {}
        ver_details = ver_data.get("verification_details") or {}
        sut_details = ver_details.get("sut") or {}
        cpu_model = sut_details.get("model", "")
        
        # 1. Detect CPU Series
        cpu_model_str = str(cpu_model).upper()
        detected_cpu_series_key = "N/A"
        if "9005" in cpu_model_str:
            detected_cpu_series_key = "AMD_EPYC_9005_Series"
        elif re.search(r'9\d{3}', cpu_model_str): 
            detected_cpu_series_key = "AMD_EPYC_9004_Series"
        elif re.search(r'8\d{3}', cpu_model_str):
            detected_cpu_series_key = "AMD_EPYC_8004_Series"
        elif re.search(r'7\d{3}', cpu_model_str):
            detected_cpu_series_key = "AMD_EPYC_7003_Series"
        elif re.search(r'7\d{2}', cpu_model_str): 
            detected_cpu_series_key = "AMD_EPYC_7002_Series"
            
        if detected_cpu_series_key == "N/A":
            raise ValueError(f"Could not detect CPU Series for model: '{cpu_model_str}'.")

        # 2. Find Tuning Profile
        tuning_profile_name = self.normalized_benchmark_map.get(benchmark_name.upper())
        if not tuning_profile_name:
            raise ValueError(f"Benchmark '{benchmark_name}' not found in benchmark_tuning_map.json")
            
        # 3. Get Standard Config from Tuning Guide
        cpu_series_profiles = self.tuning_guide.get(detected_cpu_series_key, {})
        if not cpu_series_profiles:
             raise ValueError(f"CPU Series '{detected_cpu_series_key}' not found in Tuning Guide")

        standard_config_to_use = cpu_series_profiles.get(tuning_profile_name, {})
        
        # Compatibility Logic: Explicitly allow fallback mapping for ALL supported CPU series
        if not standard_config_to_use and detected_cpu_series_key in [
            "AMD_EPYC_9005_Series",
            "AMD_EPYC_9004_Series",
            "AMD_EPYC_8004_Series",
            "AMD_EPYC_7003_Series",
            "AMD_EPYC_7002_Series"
        ]:
            legacy_profile_map = self.compatibility_map.get("legacy_profile_map", {})
            legacy_name = legacy_profile_map.get(tuning_profile_name)
            
            if legacy_name:
                logger.info(f"'{tuning_profile_name}' not found. Trying legacy name: '{legacy_name}'")
                standard_config_to_use = cpu_series_profiles.get(legacy_name, {})

        if not standard_config_to_use:
            raise ValueError(f"Profile '{tuning_profile_name}' not found for CPU '{detected_cpu_series_key}'")

        bios_matches, bios_mismatches, bios_not_found = 0, 0, 0
        grub_matches, grub_mismatches, grub_not_found = 0, 0, 0
        
        # 4. BIOS CHECK
        standard_bios = standard_config_to_use.get("BIOS_Settings", {})
        bios_total_std_settings = len(standard_bios)
        
        server_data = server_metadata.get("Data") or {}
        server_bios_data = (server_data.get("bios_settings") or server_data.get("bios_configuration") or {})
        
        if ver_data.get("turbo_status", "").lower() != 'n/a':
            server_bios_data['Core Performance Boost'] = ver_data.get("turbo_status", "").capitalize()
        if ver_data.get("Thread_per_core") in ["1", "2"]:
            server_bios_data['SMT Control'] = 'Enable' if ver_data.get("Thread_per_core") == "2" else 'Disable'
        
        bios_results = []
        all_bios_keys = sorted(list(set(standard_bios.keys()) | set(server_bios_data.keys())))
        
        for key in all_bios_keys:
            key_normalized = re.sub(r'[\s_-]', '', key).upper()
            std_key_match = next((k for k in standard_bios if re.sub(r'[\s_-]', '', k).upper() == key_normalized), None)
            
            std_val = standard_bios.get(std_key_match)
            srv_val = server_bios_data.get(key, "N/A")
            display_key = std_key_match or key

            status = ""
            if std_val is not None:
                if str(std_val).lower() == "default":
                    status, bios_matches = "Match (Standard is Default)", bios_matches + 1
                elif str(srv_val).lower() == str(std_val).lower(): 
                    status, bios_matches = "Match", bios_matches + 1
                elif srv_val == "N/A": 
                    status, bios_not_found = "Not Found", bios_not_found + 1
                else: 
                    status, bios_mismatches = "Mismatch", bios_mismatches + 1
            else: 
                status = "Server Specific"
            
            bios_results.append({'setting': display_key, 'standard_value': std_val if std_val is not None else "N/A", 'server_value': srv_val, 'status': status})

        # 5. GRUB CHECK
        standard_grub = standard_config_to_use.get("Linux_OS_Settings", {}).get("GRUB_Parameters", [])
        grub_total_std_settings = len(standard_grub)
        grub_results = []
        
        combined_grub_info = " ".join(server_data.get("fileTunings") or [])
        final_grub_str = ""
        server_grub_dict = {}

        match = re.search(r'GRUB_CMDLINE_LINUX_DEFAULT="([^"]*)"', combined_grub_info)
        if match: 
            final_grub_str = match.group(1)
            server_grub_dict = {k: v for k, v in [p.split('=', 1) if '=' in p else (p, True) for p in shlex.split(final_grub_str)]}
        
        for std_param in standard_grub:
            std_key, std_val = (std_param.split('=', 1) + [True])[:2]
            status = ""
            if std_key in server_grub_dict:
                srv_val = server_grub_dict[std_key]
                if str(srv_val) == str(std_val):
                    status, grub_matches = "Match", grub_matches + 1
                else:
                    status, grub_mismatches = f"Mismatch (Server: {srv_val})", grub_mismatches + 1
            else: 
                status, grub_not_found = "Not Found", grub_not_found + 1
            grub_results.append({'parameter': std_param, 'status': status})

        # 6. SUMMARY
        total_std_settings = bios_total_std_settings + grub_total_std_settings
        total_matches = bios_matches + grub_matches
        
        summary = {
            'profile_key': tuning_profile_name,
            'detected_cpu_series': detected_cpu_series_key,
            'overall_compliance_percent': round((total_matches / max(total_std_settings, 1) * 100), 2)
        }

        return {
            'summary': summary,
            'bios_results': bios_results,
            'grub_results': grub_results,
            'server_cpu_model': cpu_model
        }

    def run_full_audit(self, host: str, username: str, password: str, benchmark_name: str):
        # 1. Basic Connectivity Check
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            if sock.connect_ex((host, 22)) != 0:
                raise ConnectionRefusedError(f"Server '{host}' unreachable on port 22.")
        finally:
            sock.close()

        # 2. Execute Remote SSH Script (Fetches both metadata and network data)
        logger.info(f"Executing remote audit script on {host} (Full Mode)...")
        ssh_result = self._execute_network_audit_remotely(host, username, password)
        stdout = ssh_result.get("stdout", "")
        stderr = ssh_result.get("stderr", "")
        
        # 3. Parse JSON Output
        json_match = re.search(r'(\{.*\}|\[.*\])', stdout, re.DOTALL)
        if not json_match:
            error_detail = "Audit script failed to return JSON output."
            logger.error(f"{error_detail}\nStdout: {stdout}\nStderr: {stderr}")
            raise RuntimeError(error_detail)

        try:
            full_data = json.loads(json_match.group(1))
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse audit JSON: {e}")
            raise RuntimeError("Invalid JSON returned from remote script.")

        remote_metadata = full_data.get("metadata", {})
        network_data = full_data.get("network_data", {})

        # 4. Simulate API Records for Compatibility
        # This allows us to keep using _generate_reports without modification
        simulated_verification = {
            "Data": {
                "verification_details": {
                    "sut": {
                        "model": remote_metadata.get("cpu_model", "N/A"),
                        "verified": True
                    }
                },
                "turbo_status": remote_metadata.get("turbo_status", "N/A"),
                "Thread_per_core": remote_metadata.get("threads_per_core", "1")
            }
        }

        # Map inferred BIOS settings from local command outputs
        bios_findings = remote_metadata.get("bios_info", {}).copy()
        
        # Power Profile Mapping
        governor = remote_metadata.get("scaling_governor", "").lower()
        epp = remote_metadata.get("epp", "").lower()
        
        power_profile = "N/A"
        if governor == "performance":
            power_profile = "High Performance"
        elif governor == "powersave":
            power_profile = "Efficiency Mode"
            
        determinism = "N/A"
        if epp == "performance":
            determinism = "Enabled"
            
        bios_findings.update({
            'NUMA Nodes per Socket (NPS)': remote_metadata.get("nps", "N/A"),
            'Memory Target Speed': remote_metadata.get("memory_speed", "N/A"),
            'IOMMU': remote_metadata.get("iommu_status", "N/A"),
            'SVM Mode': remote_metadata.get("virtualization", "N/A"),
            'DF C-States': remote_metadata.get("cstates_info", "N/A"),
            'Power Profile Selection': power_profile,
            'Determinism Control': determinism,
            'Determinism Enable': "Performance" if epp == "performance" else "N/A"
        })

        simulated_metadata = {
            "Data": {
                "bios_settings": bios_findings,
                "fileTunings": [f'GRUB_CMDLINE_LINUX_DEFAULT="{remote_metadata.get("grub_cmdline", "")}"']
            }
        }

        # 5. Generate Compliance Report
        logger.info(f"Generating compliance report using SSH-collected metadata...")
        config_report = self._generate_reports(benchmark_name, simulated_metadata, simulated_verification)
        
        # 6. Final Formatting
        overall_status = "SUCCESS"
        if "error" in network_data:
            overall_status = "WARNING"

        return {
            "status": overall_status,
            "host": host,
            "config_report": config_report,
            "network_audit": {
                "json_report": network_data,
                "raw_output": f"--- STDOUT ---\n{stdout}\n\n--- STDERR ---\n{stderr}"
            },
            "note": "Audit performed entirely via SSH (API bypassed)."
        }

    def run_direct_network_audit(self, host: str, user: str, password: str) -> Dict[str, Any]:
        """
        Runs ONLY the network audit via SSH, bypassing the external metadata API.
        """
        logger.info(f"Running DIRECT network audit for {host} (bypassing metadata API)")
        
        try:
            # Connectivity check
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)
            result = sock.connect_ex((host, 22))
            sock.close()
            if result != 0:
                 raise ConnectionRefusedError(f"Server '{host}' unreachable on port 22.")
                 
            # Run the audit
            ssh_result = self._execute_network_audit_remotely(host, user, password)
            stdout = ssh_result.get("stdout", "")
            stderr = ssh_result.get("stderr", "")
            
            json_match = re.search(r'(\{.*\}|\[.*\])', stdout, re.DOTALL)
            network_audit_json = {}
            remote_metadata = {}
            
            if json_match:
                try:
                    full_data = json.loads(json_match.group(1))
                    network_audit_json = full_data.get("network_data", {})
                    remote_metadata = full_data.get("metadata", {})
                except json.JSONDecodeError:
                    network_audit_json = {"error": "Failed to parse JSON", "raw_stdout": stdout}
            else:
                network_audit_json = {"error": "No JSON output found", "raw_stdout": stdout, "stderr": stderr}

            return {
                "status": "SUCCESS" if "error" not in network_audit_json else "WARNING",
                "host": host,
                "network_audit": {
                    "json_report": network_audit_json,
                    "raw_output": stdout
                },
                "metadata": remote_metadata,
                "note": "Direct mode: BIOS/GRUB compliance skipped due to API bypass."
            }

        except Exception as e:
            logger.error(f"Direct audit failed: {e}")
            raise e