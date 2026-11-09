#!/bin/bash
set -u
mkdir -p /logs/verifier
cd /workspace
if timeout 20 python3 /tests/check.py; then
    printf '1' > /logs/verifier/reward.txt
else
    printf '0' > /logs/verifier/reward.txt
fi
