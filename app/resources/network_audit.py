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

def run_command(command, timeout=10):
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False, timeout=timeout)
        return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""

def get_nic_data():
    print("Gathering NIC hardware, link, and neighbor information via /sys...", file=sys.stderr)
    
    # Get all network interfaces except loopback
    interfaces = [d for d in os.listdir('/sys/class/net') if d != 'lo']
    physical_nics = {}

    for interface in interfaces:
        # Filter for physical devices (those with a 'device' link)
        device_path = f'/sys/class/net/{interface}/device'
        if not os.path.exists(device_path):
            continue
            
        # Get PCI Bus Info (e.g. 0000:01:00.0)
        bus_info = os.path.basename(os.readlink(device_path)) if os.path.islink(device_path) else interface
        
        if bus_info not in physical_nics:
            # Try to get OEM/Model from /sys
            vendor_path = f'{device_path}/vendor'
            device_id_path = f'{device_path}/device'
            
            vendor = "N/A"
            if os.path.exists(vendor_path):
                with open(vendor_path, 'r') as f: vendor = f.read().strip()
            
            model = "N/A"
            if os.path.exists(device_id_path):
                with open(device_id_path, 'r') as f: model = f.read().strip()
            
            # Get max speed / capacity (best effort)
            capacity_path = f'/sys/class/net/{interface}/speed'
            max_speed_str = "N/A"
            if os.path.exists(capacity_path):
                try:
                    with open(capacity_path, 'r') as f:
                        speed = int(f.read().strip())
                        if speed > 0: max_speed_str = f"{speed} Gbit/s" if speed >= 1000 else f"{speed} Mbit/s"
                except: pass

            physical_nics[bus_info] = {
                'oem': vendor,
                'model': model,
                'max_speed': max_speed_str,
                'ports': []
            }
            
        # Port specific info
        port = {'name': interface}
        
        # Ethtool for link speed
        ethtool_out = run_command(['ethtool', interface])
        speed_match = re.search(r'Speed:\s*(\S+)', ethtool_out)
        port['negotiated_speed'] = speed_match.group(1) if speed_match else 'Down'
        
        advertised_match = re.search(r'Advertised link modes:(.*?)Supported ports:', ethtool_out, re.DOTALL)
        port['advertised_speeds'] = advertised_match.group(1).lower().strip() if advertised_match else ""
        
        # LLDP for neighbors
        lldp_out = run_command(['lldpctl', interface, '-f', 'keyvalue'], timeout=5)
        lldp_dict = dict(re.findall(r'([^=]+)=(.*)', lldp_out))
        port['mau_type'] = lldp_dict.get('lldp.eth.mau_type', '').strip()
        sysname = lldp_dict.get('lldp.eth.chassis.name', 'N/A').strip()
        portid = lldp_dict.get('lldp.eth.port.id.value', 'N/A').strip()
        port['connected_to'] = f"{sysname} (Port: {portid})" if sysname != 'N/A' else 'N/A'
        
        physical_nics[bus_info]['ports'].append(port)
        
    return physical_nics

def get_metadata():
    print("Gathering system metadata via /sys and lscpu...", file=sys.stderr)
    metadata = {}
    
    # 1. CPU Model
    lscpu_out = run_command(['lscpu'])
    model_match = re.search(r'Model name:\s*(.*)', lscpu_out)
    metadata['cpu_model'] = model_match.group(1).strip() if model_match else "N/A"
    
    # 2. SMT / Thread per core
    thread_match = re.search(r'Thread\(s\) per core:\s*(\d+)', lscpu_out)
    metadata['threads_per_core'] = thread_match.group(1) if thread_match else "1"
    
    # 3. Turbo / CPB status
    turbo_path = "/sys/devices/system/cpu/cpufreq/boost"
    if os.path.exists(turbo_path):
        try:
            with open(turbo_path, 'r') as f:
                metadata['turbo_status'] = "Enabled" if f.read().strip() == "1" else "Disabled"
        except: metadata['turbo_status'] = "N/A"
    else:
        metadata['turbo_status'] = "N/A"
        
    # 4. System Metadata from /sys/class/dmi/id (Instant)
    dmi_path = "/sys/class/dmi/id"
    dmi_map = {
        'product_name': 'system_model',
        'bios_vendor': 'bios_vendor',
        'bios_version': 'bios_version',
        'bios_date': 'bios_date'
    }
    
    bios_info = {}
    for dmi_file, meta_key in dmi_map.items():
        file_path = os.path.join(dmi_path, dmi_file)
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r') as f:
                    val = f.read().strip()
                    if dmi_file == 'product_name': metadata[meta_key] = val
                    else: bios_info[dmi_file.replace('bios_', '')] = val
            except: pass
            
    # Fallback for bios_info if /sys fails
    if not bios_info:
        bios_info = {
            'vendor': run_command(['dmidecode', '-s', 'bios-vendor'], timeout=5).strip() or "N/A",
            'version': run_command(['dmidecode', '-s', 'bios-version'], timeout=5).strip() or "N/A",
            'release_date': run_command(['dmidecode', '-s', 'bios-release-date'], timeout=5).strip() or "N/A",
        }
    metadata['bios_info'] = bios_info
        
    # 5. GRUB Parameters
    cmdline_path = '/proc/cmdline'
    if os.path.exists(cmdline_path):
        with open(cmdline_path, 'r') as f:
            metadata['grub_cmdline'] = f.read().strip()
    else:
        metadata['grub_cmdline'] = "N/A"

    # 6. NPS (NUMA Nodes per Socket) - INFERRED
    numa_nodes = [d for d in os.listdir('/sys/devices/system/node') if d.startswith('node')]
    metadata['nps'] = str(len(numa_nodes)) if numa_nodes else "1"

    # 7. Memory Speed
    mem_out = run_command(['dmidecode', '-t', 'memory'], timeout=10)
    speed_match = re.search(r'Configured Memory Speed:\s*(\d+\s*MT/s)', mem_out)
    metadata['memory_speed'] = speed_match.group(1) if speed_match else "N/A"

    # 8. IOMMU Status
    metadata['iommu_status'] = "Enabled" if os.path.exists('/sys/class/iommu') and os.listdir('/sys/class/iommu') else "Disabled"

    # 9. Virtualization / SVM
    with open('/proc/cpuinfo', 'r') as f:
        cpu_info_content = f.read()
        metadata['virtualization'] = "Enabled" if 'svm' in cpu_info_content or 'vmx' in cpu_info_content else "Disabled"

    # 10. Idle States (C-States)
    metadata['cstates_info'] = "Enabled" if os.path.exists('/sys/devices/system/cpu/cpuidle') else "Disabled"

    # 11. Scaling Governor (Infers Power Profile)
    gov_path = "/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"
    if os.path.exists(gov_path):
        with open(gov_path, 'r') as f:
            metadata['scaling_governor'] = f.read().strip()
    else:
        metadata['scaling_governor'] = "N/A"

    # 12. Energy Performance Preference (EPP)
    epp_path = "/sys/devices/system/cpu/cpu0/cpufreq/energy_performance_preference"
    if os.path.exists(epp_path):
        with open(epp_path, 'r') as f:
            metadata['epp'] = f.read().strip()
    else:
        metadata['epp'] = "N/A"
    
    return metadata

def main():
    # Root check (Linux/Unix only)
    if hasattr(os, "geteuid"):
        if os.geteuid() != 0:
            print("This script must be run as root.", file=sys.stderr)
            print(json.dumps({"error": "Script not run as root"}))
            sys.exit(1)
    
    try:
        check_dependencies()
        nic_data = get_nic_data()
        metadata = get_metadata()
        
        output = {
            "network_data": nic_data,
            "metadata": metadata
        }
        
        print(json.dumps(output, indent=2))
        
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

if __name__ == "__main__":
    main()
