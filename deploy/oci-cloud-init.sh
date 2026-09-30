#!/bin/bash
# Paste into OCI > Create instance > Advanced options > Management > cloud-init script.
# Keep this file plain ASCII: the OCI console rejects other characters.
# No secrets here (instance metadata is readable on the VM). Afterwards: ssh in,
# fill ~/stock-insights/backend/.env, run: bash ~/stock-insights/deploy/oracle-setup.sh
LOG=/var/log/stockpilot-setup.log
touch "$LOG" && chown ubuntu:ubuntu "$LOG"
sudo -u ubuntu -i bash -c '
  curl -fsSL https://raw.githubusercontent.com/saikovuri/Stock_Insights_dashboard/master/deploy/oracle-setup.sh -o ~/setup.sh &&
  bash ~/setup.sh
' >> "$LOG" 2>&1
echo "StockPilot first-boot setup finished (exit $?)" >> "$LOG"
