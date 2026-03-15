#!/usr/bin/env bash
# Run this script on the Ubuntu 22 server as a user with sudo access.
# Usage: bash setup.sh
set -euo pipefail

APP_DIR="/opt/vr-ops-rag"
SERVICE_USER="vrops"

echo "=== VR-OPS RAG — server setup ==="

# ── 1. System dependencies ──────────────────────────────────────────────────
echo "[1/6] Installing system packages..."
sudo apt-get update -q
sudo apt-get install -y python3.11 python3.11-venv python3.11-dev git curl

# ── 2. Create a dedicated service user ──────────────────────────────────────
echo "[2/6] Creating service user '$SERVICE_USER'..."
if ! id "$SERVICE_USER" &>/dev/null; then
    sudo useradd --system --shell /bin/bash --create-home "$SERVICE_USER"
fi

# ── 3. Create app directory and copy files ───────────────────────────────────
echo "[3/6] Setting up app directory at $APP_DIR..."
sudo mkdir -p "$APP_DIR"
sudo rsync -a --exclude '.venv' --exclude '.git' --exclude 'data' \
    "$(dirname "$(realpath "$0")")/../" "$APP_DIR/"
sudo chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

# ── 4. Python virtual environment and dependencies ──────────────────────────
echo "[4/6] Creating Python venv and installing dependencies..."
sudo -u "$SERVICE_USER" python3.11 -m venv "$APP_DIR/.venv"
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"

# ── 5. .env file ─────────────────────────────────────────────────────────────
ENV_FILE="$APP_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "[5/6] Creating .env file (you must add your OPENAI_API_KEY)..."
    sudo tee "$ENV_FILE" > /dev/null <<'EOF'
OPENAI_API_KEY=sk-YOUR_KEY_HERE
OPENAI_LLM_MODEL=gpt-4o-mini
CHROMA_PATH=/opt/vr-ops-rag/data/chroma
MAX_TOKENS=400

# Local embeddings via Ollama (comment out to use OpenAI embeddings instead)
OLLAMA_BASE_URL=http://localhost:11434
# EMBED_MODEL=nomic-embed-text  # default when OLLAMA_BASE_URL is set
EOF
    sudo chown "$SERVICE_USER:$SERVICE_USER" "$ENV_FILE"
    sudo chmod 600 "$ENV_FILE"
    echo "  *** Edit $ENV_FILE and set your OPENAI_API_KEY before starting services ***"
else
    echo "[5/6] .env already exists — skipping."
fi

# ── 6. Install systemd services ──────────────────────────────────────────────
echo "[6/6] Installing systemd services..."
sudo cp "$(dirname "$(realpath "$0")")/vrops-api.service" /etc/systemd/system/
sudo cp "$(dirname "$(realpath "$0")")/vrops-dashboard.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable vrops-api vrops-dashboard

# ── Firewall ─────────────────────────────────────────────────────────────────
echo "Opening firewall ports 8000 and 8051..."
sudo ufw allow 8000/tcp comment "VR-OPS API"
sudo ufw allow 8051/tcp comment "VR-OPS Dashboard"

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Edit your API key:  sudo nano $ENV_FILE"
echo "  2. Start services:     sudo systemctl start vrops-api vrops-dashboard"
echo "  3. Check status:       sudo systemctl status vrops-api vrops-dashboard"
echo "  4. View logs:          sudo journalctl -u vrops-api -f"
echo "                         sudo journalctl -u vrops-dashboard -f"
echo ""
echo "  API:       http://10.44.122.161:8000"
echo "  API docs:  http://10.44.122.161:8000/docs"
echo "  Dashboard: http://10.44.122.161:8051"
