#!/bin/bash
# EC2 user-data: bootstrap a PyKV cluster + dashboard on Amazon Linux 2023.
# The deploy script substitutes __REPO_URL__ before launch.
set -euo pipefail
dnf install -y python3.11 python3.11-pip git
git clone __REPO_URL__ /opt/pykv
python3.11 -m pip install fastapi uvicorn requests

cat > /etc/systemd/system/pykv.service <<'EOF'
[Unit]
Description=PyKV distributed key-value cluster
After=network.target

[Service]
WorkingDirectory=/opt/pykv
ExecStart=/usr/bin/python3.11 launch_cluster.py --nodes 3 --host 0.0.0.0 --revive 15
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now pykv
