#!/bin/bash

# API address
API_URL="http://localhost:8000/post_flight_check/EXECUTION_123"

# Example Benchmark Data (Sample from scoring.py expected structure)
# This mimics what the external API used to return.
DATA='{
  "data": [
    {
      "platformProfilerData": {
        "Summary": {
          "Server": { "Model": "EPYC 9005 Test", "Manufacturer": "AMD", "CPUModel": "9654" },
          "BIOS": { "BIOSVersion": "1.0", "Microcode": "0x123", "SMTControl": "Enabled" },
          "CPU": { "Architecture": "x86_64", "Socket(s)": "2", "CPU(s)": "192", "Thread(s)PerCore": "2", "Core(s)PerSocket": "96" },
          "OS": { "OperatingSystem": "Ubuntu 22.04", "Kernel": "5.15.0" },
          "Memory": { "Total": "512GB" },
          "Tunings": { "GccVersion": "11.2", "TransparentHugepage": "always", "security": "off", "compilerOptions": "-O3" }
        }
      },
      "runs": [
        {
          "iterations": [
            {
              "instances": [
                {
                  "metricsInfo": { "score": 100 }
                }
              ]
            }
          ]
        }
      ]
    }
  ]
}'

echo "=== Mode A: Manual ID Lookup (DB) ==="
echo "Triggering Post-Flight Check with ID only (fetching from local DB)..."
curl -s -X POST "$API_URL" | python3 -m json.tool

echo -e "\n=== Mode B: Manual Data Submission (JSON) ==="
echo "Triggering Post-Flight Check with manual data payload..."
curl -s -X POST "$API_URL" \
     -H "Content-Type: application/json" \
     -d "$DATA" | python3 -m json.tool
