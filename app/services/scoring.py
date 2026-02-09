# app/services/scoring.py
from typing import Dict, Any, Tuple

EXPECTED_PROFILER_FIELDS = {
    "Summary": {
        "Server": ["Model", "Manufacturer", "CPUModel"],
        "BIOS": ["BIOSVersion", "Microcode", "SMTControl"],
        "CPU": ["Architecture", "Socket(s)", "CPU(s)", "Thread(s)PerCore", "Core(s)PerSocket"],
        "OS": ["OperatingSystem", "Kernel"],
        "Memory": ["Total"],
        "Network": [],
        "Disk": [],
        "Tunings": ["GccVersion", "TransparentHugepage", "security", "compilerOptions"]
    },
}

def validate_and_score_benchmark_data(data: Dict[str, Any]) -> Tuple[bool, str, float, Dict[str, Any]]:
    # Logic from Prod_pre_post/main.py
    profiler_details = {"fields_checked": 0, "fields_present_and_valid": 0, "missing_or_empty": {}}
    basic_pass = True
    pass_fail_reasons = []

    if not isinstance(data.get("data"), list) or not data["data"]:
        return False, "FAIL: 'data' array is missing or empty in the API response.", 0.0, profiler_details

    try:
        benchmark_result = data["data"][0]
        profiler_data = benchmark_result.get("platformProfilerData")
        runs_data = benchmark_result.get("runs")
    except (IndexError, AttributeError):
        return False, "FAIL: Invalid top-level structure in benchmark data.", 0.0, profiler_details

    # Basic Checks
    if not isinstance(profiler_data, dict) or not profiler_data:
        pass_fail_reasons.append("platformProfilerData missing or empty.")
        basic_pass = False
        return basic_pass, "FAIL: " + " | ".join(pass_fail_reasons), 0.0, profiler_details

    metrics_found = False
    if not runs_data or not isinstance(runs_data, list) or not runs_data:
        pass_fail_reasons.append("'runs' section missing or empty.")
        basic_pass = False
    else:
        try:
            if runs_data[0].get("iterations", [])[0].get("instances", [])[0].get("metricsInfo"):
                metrics_found = True
        except (IndexError, TypeError, AttributeError):
            metrics_found = False

        if not metrics_found:
            pass_fail_reasons.append("No metricsInfo found.")
            basic_pass = False
    
    # --- FIX START: Return immediately if basic checks fail ---
    if not basic_pass:
        # Return 0.0 score and the specific failure reason(s)
        return basic_pass, "FAIL: " + " | ".join(pass_fail_reasons), 0.0, profiler_details
    # --- FIX END ---

    # Compliance scoring
    for section, sub_elements in EXPECTED_PROFILER_FIELDS.items():
        profiler_details["missing_or_empty"][section] = {}
        section_data = profiler_data.get(section)

        if not section_data:
            if isinstance(sub_elements, dict):
                for sub_section, fields in sub_elements.items():
                    profiler_details["fields_checked"] += len(fields)
                    profiler_details["missing_or_empty"][section][sub_section] = [f"{f} (Section Missing)" for f in fields]
            continue

        if isinstance(sub_elements, dict):
            for sub_section, fields in sub_elements.items():
                profiler_details["missing_or_empty"][section][sub_section] = []
                sub_section_data = section_data.get(sub_section)
                if not isinstance(sub_section_data, dict):
                    profiler_details["fields_checked"] += len(fields)
                    profiler_details["missing_or_empty"][section][sub_section] = [f"{f} (Missing/Invalid)" for f in fields]
                    continue

                for field in fields:
                    profiler_details["fields_checked"] += 1
                    value = sub_section_data.get(field)
                    if value not in (None, "", [], {}):
                        profiler_details["fields_present_and_valid"] += 1
                    else:
                        profiler_details["missing_or_empty"][section][sub_section].append(field)

    compliance_score = 0.0
    if profiler_details["fields_checked"] > 0:
        compliance_score = round(
            (profiler_details["fields_present_and_valid"] / profiler_details["fields_checked"]) * 100, 2
        )

    cleaned_missing = {}
    for section, subs in profiler_details["missing_or_empty"].items():
        cleaned = {k: v for k, v in subs.items() if v}
        if cleaned:
            cleaned_missing[section] = cleaned
    profiler_details["missing_or_empty"] = cleaned_missing

    msg_prefix = "PASS" if basic_pass else "FAIL"
    msg = f"{msg_prefix}: Basic checks {'passed' if basic_pass else 'failed'}. Score={compliance_score}%"


