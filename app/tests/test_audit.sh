#!/bin/bash

# API address provided by root
API_URL="http://10.159.20.87:8000/network_audit_direct"

# Target server details
HOST="10.86.26.104"
USERNAME="amd"
PASSWORD="amd1234!"

echo "Triggering Direct Network Audit Task at $API_URL..."

curl -s -X POST "$API_URL" \
     -H "Content-Type: application/json" \
     -d "{
           \"host\": \"$HOST\",
           \"username\": \"$USERNAME\",
           \"password\": \"$PASSWORD\"
         }" | python3 -m json.tool

echo -e "\n----------------------------------------"
echo "Check your Celery worker logs for the execution details."
echo "----------------------------------------"
