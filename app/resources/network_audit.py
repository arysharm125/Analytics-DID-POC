#!/usr/bin/env python3
import os
import sys
import subprocess
import re
import shutil
import json

class colors:
    WARNING = '\033[91m'
    INFO = '\033[94m'
    HEADER = '\033[95m'
    OKGREEN = '\033[92m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

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
            
            speed_match = re.search(r'Speed:\s*(\S+)', ethtool_out)
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
    # Root check (Linux/Unix only)
    if hasattr(os, "geteuid"):
        if os.geteuid() != 0:
            print("This script must be run as root.", file=sys.stderr)
            print(json.dumps({"error": "Script not run as root"}))
            sys.exit(1)
    else:
        # On Windows, we can't easily check for 'root', but this script is likely intended for Linux.
        # We'll warn but proceed, though subsequent commands (unknown to Windows) may fail.
        print(f"{colors.WARNING}Warning: Not running on a POSIX system. 'lshw', 'ethtool' may be missing.{colors.ENDC}", file=sys.stderr)
    
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
