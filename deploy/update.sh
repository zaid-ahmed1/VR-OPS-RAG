#!/usr/bin/env bash
# Quick-deploy: pull latest code and restart services.
# Usage: bash deploy/update.sh
set -euo pipefail

APP_DIR="/opt/vr-ops-rag"
SERVICE_USER="vrops"

echo "=== VR-OPS RAG — update ==="

# Pull latest code
echo "[1/3] Pulling latest code..."
sudo -u "$SERVICE_USER" git -C "$APP_DIR" pull --ff-only

# Install any new/changed dependencies
echo "[2/3] Updating Python dependencies..."
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

# Restart services
echo "[3/3] Restarting services..."
sudo systemctl restart vrops-api vrops-dashboard vrops-postgrest

echo ""
echo "Done. Checking status..."
sudo systemctl status vrops-api vrops-dashboard vrops-postgrest --no-pager -l
