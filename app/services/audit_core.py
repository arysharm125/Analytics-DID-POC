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

# Embedded remote network audit script
NETWORK_EVALUATOR_SCRIPT_CONTENT = """
#!/usr/bin/env python3
import os
import sys
import subprocess
import re
import shutil
import json

class colors:
    WARNING = '\\033[91m'
    INFO = '\\033[94m'
    HEADER = '\\033[95m'
    OKGREEN = '\\033[92m'
    ENDC = '\\033[0m'
    BOLD = '\\033[1m'

def check_dependencies():
    required_tools = ['ethtool', 'lldpctl', 'lshw']
    missing_tools = [tool for tool in required_tools if not shutil.which(tool)]
    if missing_tools:
        # This shouldn't happen if the wrapper bash script did its job
        print(f"{colors.WARNING}Error: Missing required tools: {', '.join(missing_tools)}.{colors.ENDC}", file=sys.stderr)
        sys.exit(1)

def run_command(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        return result.stdout
    except FileNotFoundError:
        return ""

def get_nic_data():
    print("Gathering hardware, link, and neighbor information...", file=sys.stderr)
    lshw_json_output = run_command(['lshw', '-c', 'network', '-json'])
    if not lshw_json_output:
        return None
    
    try:
        lshw_data = json.loads(lshw_json_output)
        if not isinstance(lshw_data, list):
            lshw_data = [lshw_data]
    except json.JSONDecodeError:
        print(f"{colors.WARNING}Error: Could not parse lshw JSON output.{colors.ENDC}", file=sys.stderr)
        return None

    physical_nics = {}
    for nic in lshw_data:
        if 'logicalname' in nic and nic.get('configuration', {}).get('driver'):
            bus_info = nic.get('businfo', nic['logicalname'])
            if bus_info not in physical_nics:
                max_speed_val = nic.get('capacity')
                max_speed_str = f"{int(max_speed_val) / 1e9:.0f} Gbit/s" if isinstance(max_speed_val, int) and max_speed_val > 0 else "N/A"
                physical_nics[bus_info] = {
                    'oem': nic.get('vendor', 'N/A'),
                    'model': nic.get('product', 'N/A'),
                    'max_speed': max_speed_str,
                    'ports': []
                }
            physical_nics[bus_info]['ports'].append({'name': nic['logicalname']})
    
    for bus_info in physical_nics:
        for port in physical_nics[bus_info]['ports']:
            interface = port['name']
            ethtool_out = run_command(['ethtool', interface])
            lldp_out = run_command(['lldpctl', interface, '-f', 'keyvalue'])
            
            speed_match = re.search(r'Speed:\\s*(\\S+)', ethtool_out)
            port['negotiated_speed'] = speed_match.group(1) if speed_match else 'Down'
            
            advertised_match = re.search(r'Advertised link modes:(.*?)Supported ports:', ethtool_out, re.DOTALL)
            port['advertised_speeds'] = advertised_match.group(1).lower().strip() if advertised_match else ""
            
            lldp_dict = dict(re.findall(r'([^=]+)=(.*)', lldp_out))
            port['mau_type'] = lldp_dict.get('lldp.eth.mau_type', '').strip()
            sysname = lldp_dict.get(f'lldp.eth.chassis.name', 'N/A').strip()
            portid = lldp_dict.get(f'lldp.eth.port.id.value', 'N/A').strip()
            port['connected_to'] = f"{sysname} (Port: {portid})" if sysname != 'N/A' else 'N/A'
    
    return physical_nics

def main():
    if os.geteuid() != 0:
        print("This script must be run as root.", file=sys.stderr)
        print(json.dumps({"error": "Script not run as root"}))
        sys.exit(1)
    
    try:
        check_dependencies()
        nic_data = get_nic_data()
        if nic_data is not None:
            print(json.dumps(nic_data, indent=2))
        else:
            print(json.dumps({"error": "Failed to retrieve NIC data"}))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    main()
"""

class ServerAuditEngine:
    def __init__(self, 
                 tuning_guide_file: str = "AMD_EPYC_Series_BIOS_Tuning_Guide.json",
                 benchmark_map_file: str = "benchmark_tuning_map.json",
                 compatibility_map_file: str = "profile_compatibility_map.json"):
        
        # Auto-resolve paths to app/resources/
        self.tuning_guide_path = os.path.join(RESOURCES_DIR, tuning_guide_file)
        self.benchmark_map_path = os.path.join(RESOURCES_DIR, benchmark_map_file)
        self.compatibility_map_path = os.path.join(RESOURCES_DIR, compatibility_map_file)
        
        # Load resources
        self.tuning_guide = self._load_json_file(self.tuning_guide_path, "Tuning Guide")
        self.benchmark_map = self._load_json_file(self.benchmark_map_path, "Benchmark Map")
        self.compatibility_map = self._load_json_file(self.compatibility_map_path, "Compatibility Map")
        
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

    def _execute_curl_command(self, curl_cmd_list: list, cmd_description: str) -> Optional[str]:
        try:
            result = subprocess.run(curl_cmd_list, capture_output=True, text=True, check=True, timeout=90)
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
{NETWORK_EVALUATOR_SCRIPT_CONTENT}
EOF

chmod +x $SCRIPT_PATH

# 2. Execute with SUDO: Install Dependencies & Run Script
# We pipe the password to sudo. The bash script inside checks and installs tools.
echo "{password}" | sudo -S -p "" bash -c '
    # Function to check if a command exists
    command_exists() {{
        command -v "$1" >/dev/null 2>&1
    }}

    # Check for required tools
    NEEDS_INSTALL=0
    if ! command_exists lldpctl; then NEEDS_INSTALL=1; fi
    if ! command_exists ethtool; then NEEDS_INSTALL=1; fi
    if ! command_exists lshw; then NEEDS_INSTALL=1; fi

    if [ $NEEDS_INSTALL -eq 1 ]; then
        echo "Installing missing dependencies (lldpd, ethtool, lshw)..." >&2
        
        if command_exists apt-get; then
            export DEBIAN_FRONTEND=noninteractive
            apt-get update -qq >/dev/null
            apt-get install -y -qq lldpd ethtool lshw >/dev/null
            service lldpd start >/dev/null 2>&1 || true
        elif command_exists dnf; then
            dnf install -y -q lldpad ethtool lshw >/dev/null
            systemctl start lldpad >/dev/null 2>&1 || true
        elif command_exists yum; then
            yum install -y -q lldpad ethtool lshw >/dev/null
            systemctl start lldpad >/dev/null 2>&1 || true
        else
            echo "Warning: Could not detect package manager to install dependencies." >&2
        fi
        
        # Give LLDPD a moment to start and collect neighbor info
        sleep 5
    fi

    # Run the Python Audit Script
    python3 {script_path}
'

# 3. Cleanup
rm -f $SCRIPT_PATH
"""
        local_command = [
            "sshpass", "-p", password,
            "ssh", "-tt", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
            f"{user}@{host}", remote_command_block
        ]

        try:
            result = subprocess.run(local_command, capture_output=True, text=True, check=False, timeout=300) # Increased timeout for installation
            if result.returncode != 0:
                logger.error(f"SSH command returned {result.returncode}")
            return {"stdout": result.stdout, "stderr": result.stderr}

        except FileNotFoundError:
            raise EnvironmentError("`sshpass` not installed locally.")
        except subprocess.TimeoutExpired:
            raise TimeoutError("SSH connection timed out (possibly during installation).")
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
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5)
            if sock.connect_ex((host, 22)) != 0:
                raise ConnectionRefusedError(f"Server '{host}' unreachable on port 22.")
        finally:
            sock.close()

        verification = self._verify_resources(host, username, password)
        if not verification:
            raise ConnectionRefusedError("Verification API returned no data.")
        
        ver_data = verification.get("Data") or {}
        ver_details = ver_data.get("verification_details") or {}
        sut = ver_details.get("sut") or {}
        
        if not sut.get("verified"):
            error_msg = sut.get("error", "API check failed.")
            raise ConnectionRefusedError(f"Authentication Failed. API Error: {error_msg}")

        metadata = self._get_combined_metadata(host, username, password)
        if not metadata:
            raise ValueError("Failed to fetch server metadata.")

        config_report = self._generate_reports(benchmark_name, metadata, verification)
        
        tuning_profile = config_report.get("summary", {}).get("profile_key", "").lower()
        run_network_audit = False
        if "nic" in tuning_profile or "telco" in tuning_profile or "vran" in tuning_profile:
            run_network_audit = True
            
        network_audit_json = {"status": "SKIPPED", "reason": "Benchmark does not require network audit."}
        raw_network_output = "--- SKIPPED ---"

        if run_network_audit:
            logger.info(f"Running network audit for profile: {tuning_profile}")
            # This call now performs auto-installation
            network_output = self._execute_network_audit_remotely(host, username, password)
            stdout = network_output.get("stdout", "")
            stderr = network_output.get("stderr", "")
            raw_network_output = f"--- STDOUT ---\n{stdout}\n\n--- STDERR ---\n{stderr}"

            json_match = re.search(r'(\{.*\}|\[.*\])', stdout, re.DOTALL)
            if json_match:
                try:
                    network_audit_json = json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    network_audit_json = {"error": "Failed to parse JSON", "raw_stdout": stdout}
            else:
                error_detail = "Network audit returned no output to stdout."
                network_audit_json = {"error": error_detail}
        
        overall_status = "SUCCESS"
        if "error" in network_audit_json and run_network_audit:
            overall_status = "WARNING" 

        return {
            "status": overall_status,
            "host": host,
            "config_report": config_report,
            "network_audit": {
                "json_report": network_audit_json,
                "raw_output": raw_network_output
            }
        }