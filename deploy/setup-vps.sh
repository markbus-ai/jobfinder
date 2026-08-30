#!/usr/bin/env bash
set -euo pipefail

# JobFinder VPS Setup (without Docker)
# Usage: ./setup-vps.sh

echo "🔧 Setting up JobFinder on VPS..."

# 1. Create user
sudo useradd -r -s /bin/false jobfinder 2>/dev/null || true

# 2. Clone repo
sudo git clone https://github.com/markbus-ai/jobfinder.git /opt/jobfinder
sudo chown -R jobfinder:jobfinder /opt/jobfinder

# 3. Python venv
sudo -u jobfinder python3 -m venv /opt/jobfinder/venv
sudo -u jobfinder /opt/jobfinder/venv/bin/pip install -r /opt/jobfinder/requirements.txt

# 4. Install Typst
ARCH=$(dpkg --print-architecture)
if [ "$ARCH" = "amd64" ]; then TARCH="x86_64"; fi
curl -fsSL "https://github.com/typst/typst/releases/download/v0.15.1/typst-x86_64-unknown-linux-musl.tar.xz" -o /tmp/typst.tar.xz
sudo tar -xf /tmp/typst.tar.xz -C /tmp
sudo mv /tmp/typst-x86_64-unknown-linux-musl/typst /usr/local/bin/typst
sudo chmod +x /usr/local/bin/typst
rm -rf /tmp/typst*

# 5. Copy Typst templates
sudo mkdir -p /home/jobfinder/.config/cvs
sudo cp /opt/jobfinder/.typst-templates/*.typ /home/jobfinder/.config/cvs/ 2>/dev/null || true
sudo chown -R jobfinder:jobfinder /home/jobfinder/.config

# 6. Create data dir
sudo -u jobfinder mkdir -p /opt/jobfinder/data

# 7. Install systemd service
sudo cp /opt/jobfinder/deploy/jobfinder.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable jobfinder

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. Copy .env.example to .env and fill in your keys:"
echo "     sudo -u jobfinder cp /opt/jobfinder/.env.example /opt/jobfinder/.env"
echo "     sudo -u jobfinder nano /opt/jobfinder/.env"
echo ""
echo "  2. Copy your Typst templates:"
echo "     sudo cp ~/.config/cvs/*.typ /home/jobfinder/.config/cvs/"
echo ""
echo "  3. Start the service:"
echo "     sudo systemctl start jobfinder"
echo ""
echo "  4. Check logs:"
echo "     sudo journalctl -u jobfinder -f"
