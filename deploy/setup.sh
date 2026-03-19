#!/usr/bin/env bash
# Run this script on the Ubuntu 22 server as a user with sudo access.
# Usage: bash setup.sh
set -euo pipefail

APP_DIR="/opt/vr-ops-rag"
SERVICE_USER="vrops"
POSTGREST_VERSION="v12.2.3"
DB_NAME="vrops"
DB_AUTH_ROLE="vrops_authenticator"

echo "=== VR-OPS RAG — server setup ==="

# ── 1. System dependencies ───────────────────────────────────────────────────
echo "[1/9] Installing system packages..."
sudo apt-get update -q
sudo apt-get install -y python3.11 python3.11-venv python3.11-dev git curl \
    nginx postgresql postgresql-contrib

# ── 2. Create a dedicated service user ──────────────────────────────────────
echo "[2/9] Creating service user '$SERVICE_USER'..."
if ! id "$SERVICE_USER" &>/dev/null; then
    sudo useradd --system --shell /bin/bash --create-home "$SERVICE_USER"
fi

# ── 3. Create app directory and copy files ───────────────────────────────────
echo "[3/9] Setting up app directory at $APP_DIR..."
sudo mkdir -p "$APP_DIR"
sudo rsync -a --exclude '.venv' --exclude '.git' --exclude 'data' \
    "$(dirname "$(realpath "$0")")/../" "$APP_DIR/"
sudo chown -R "$SERVICE_USER:$SERVICE_USER" "$APP_DIR"

# ── 4. Python virtual environment and dependencies ──────────────────────────
echo "[4/9] Creating Python venv and installing dependencies..."
sudo -u "$SERVICE_USER" python3.11 -m venv "$APP_DIR/.venv"
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install --quiet --upgrade pip
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install --quiet -r "$APP_DIR/requirements.txt"
sudo -u "$SERVICE_USER" "$APP_DIR/.venv/bin/pip" install --quiet psycopg2-binary

# ── 5. PostgreSQL setup ───────────────────────────────────────────────────────
echo "[5/9] Setting up PostgreSQL..."

# Generate a random password for the PostgREST authenticator role
DB_PASSWORD=$(openssl rand -base64 32 | tr -d '/+=\n')

# Create database and run schema
sudo -u postgres psql -v ON_ERROR_STOP=1 <<SQL
CREATE DATABASE $DB_NAME;
SQL

sudo -u postgres psql -d "$DB_NAME" -v ON_ERROR_STOP=1 -f "$APP_DIR/deploy/schema.sql"

# Set the authenticator password
sudo -u postgres psql -d "$DB_NAME" -v ON_ERROR_STOP=1 \
    -c "ALTER ROLE $DB_AUTH_ROLE WITH LOGIN PASSWORD '$DB_PASSWORD';"

echo "  PostgreSQL database '$DB_NAME' created."

# ── 6. .env file ─────────────────────────────────────────────────────────────
ENV_FILE="$APP_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    echo "[6/9] Creating .env file..."
    sudo tee "$ENV_FILE" > /dev/null <<EOF
OPENAI_API_KEY=sk-YOUR_KEY_HERE
OPENAI_LLM_MODEL=gpt-4o-mini
CHROMA_PATH=/opt/vr-ops-rag/data/chroma
MAX_TOKENS=400

# Local embeddings via Ollama (comment out to use OpenAI embeddings instead)
OLLAMA_BASE_URL=http://localhost:11434

# PostgreSQL / PostgREST
POSTGREST_URL=http://localhost:3000
PGRST_DB_URI=postgresql://${DB_AUTH_ROLE}:${DB_PASSWORD}@localhost:5432/${DB_NAME}
PGRST_DB_SCHEMA=public
PGRST_DB_ANON_ROLE=vrops_api
PGRST_SERVER_PORT=3000
PGRST_DB_POOL=10
EOF
    sudo chown "$SERVICE_USER:$SERVICE_USER" "$ENV_FILE"
    sudo chmod 600 "$ENV_FILE"
    echo "  *** Edit $ENV_FILE and set your OPENAI_API_KEY before starting services ***"
else
    echo "[6/9] .env already exists — appending PostgREST vars if missing..."
    grep -q "PGRST_DB_URI" "$ENV_FILE" || sudo tee -a "$ENV_FILE" > /dev/null <<EOF

# PostgreSQL / PostgREST (added by setup.sh)
POSTGREST_URL=http://localhost:3000
PGRST_DB_URI=postgresql://${DB_AUTH_ROLE}:${DB_PASSWORD}@localhost:5432/${DB_NAME}
PGRST_DB_SCHEMA=public
PGRST_DB_ANON_ROLE=vrops_api
PGRST_SERVER_PORT=3000
PGRST_DB_POOL=10
EOF
fi

# ── 7. PostgREST binary ───────────────────────────────────────────────────────
echo "[7/9] Installing PostgREST $POSTGREST_VERSION..."
PGRST_ARCHIVE="postgrest-${POSTGREST_VERSION}-linux-static-x64.tar.xz"
PGRST_URL="https://github.com/PostgREST/postgrest/releases/download/${POSTGREST_VERSION}/${PGRST_ARCHIVE}"
curl -fsSL "$PGRST_URL" -o "/tmp/$PGRST_ARCHIVE"
sudo tar -xJ -C /usr/local/bin -f "/tmp/$PGRST_ARCHIVE"
sudo chmod +x /usr/local/bin/postgrest
rm -f "/tmp/$PGRST_ARCHIVE"
echo "  PostgREST installed at /usr/local/bin/postgrest"

# ── 8. Install systemd services ──────────────────────────────────────────────
echo "[8/9] Installing systemd services..."
sudo cp "$APP_DIR/deploy/vrops-api.service"        /etc/systemd/system/
sudo cp "$APP_DIR/deploy/vrops-dashboard.service"  /etc/systemd/system/
sudo cp "$APP_DIR/deploy/vrops-postgrest.service"  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable vrops-api vrops-dashboard vrops-postgrest

# ── 9. Nginx config and firewall ─────────────────────────────────────────────
echo "[9/9] Configuring Nginx and firewall..."
sudo cp "$APP_DIR/deploy/nginx.conf" /etc/nginx/sites-available/vr-ops
sudo ln -sf /etc/nginx/sites-available/vr-ops /etc/nginx/sites-enabled/vr-ops
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl enable nginx

# Replace direct port access with port 80/443 only
sudo ufw delete allow 8000/tcp 2>/dev/null || true
sudo ufw delete allow 8051/tcp 2>/dev/null || true
sudo ufw allow 80/tcp   comment "HTTP (Nginx)"
sudo ufw allow 443/tcp  comment "HTTPS (Nginx)"
sudo ufw allow 22/tcp   comment "SSH"

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. Set your API key:   sudo nano $ENV_FILE"
echo "  2. Migrate xlsx data:  sudo -u vrops $APP_DIR/.venv/bin/python $APP_DIR/deploy/migrate_xlsx.py \\"
echo "                             --db \"postgresql://${DB_AUTH_ROLE}:${DB_PASSWORD}@localhost:5432/${DB_NAME}\""
echo "  3. Start services:     sudo systemctl start vrops-postgrest vrops-api vrops-dashboard nginx"
echo "  4. Check status:       sudo systemctl status vrops-postgrest vrops-api vrops-dashboard"
echo "  5. View logs:          sudo journalctl -u vrops-api -f"
echo "                         sudo journalctl -u vrops-postgrest -f"
echo ""
echo "  Dashboard: http://$(hostname -I | awk '{print $1}')"
echo "  API docs:  http://$(hostname -I | awk '{print $1}')/api/docs"
echo ""
echo "  DB password stored in: $ENV_FILE"
