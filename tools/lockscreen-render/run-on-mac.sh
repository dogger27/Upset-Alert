#!/bin/bash
cd /tmp || exit 1
echo "--- parse the shipping widget file"
swiftc -parse UpsetAlertActivity.swift 2>&1 | head -3
echo "--- compile + run the harness"
swiftc -O seedpills.swift -o seedpills 2>&1 | grep -E "error" | head -5
./seedpills
