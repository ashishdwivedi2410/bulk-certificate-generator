#!/usr/bin/env bash
# ONE-TIME preparation of a fresh Ubuntu 22.04/24.04 EC2 instance.
# Run on the server:   bash setup_ec2.sh <git-repo-url>
#   e.g.               bash setup_ec2.sh git@github.com:YOUR_USER/bulk-certificate-generator.git
set -euo pipefail

REPO_URL="${1:?Usage: setup_ec2.sh <git-repo-url>}"
APP_DIR="/opt/bulk-certificate-generator"

echo "==> Installing packages"
sudo apt-get update -y
sudo apt-get install -y ca-certificates curl git nginx

echo "==> Installing Docker (official script, includes the compose plugin)"
if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sudo sh
fi
sudo usermod -aG docker "$USER"   # takes effect on next login

echo "==> Cloning the repository into $APP_DIR"
sudo mkdir -p "$APP_DIR"
sudo chown "$USER":"$USER" "$APP_DIR"
if [ ! -d "$APP_DIR/.git" ]; then
  git clone "$REPO_URL" "$APP_DIR"
fi

echo "==> Configuring nginx (port 80 -> app on 8000)"
sudo cp "$APP_DIR/devops/nginx/default.conf" /etc/nginx/sites-available/certificates
sudo ln -sf /etc/nginx/sites-available/certificates /etc/nginx/sites-enabled/certificates
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl enable --now nginx
sudo systemctl reload nginx

cat <<MSG

Server is prepared. Next:
  1. LOG OUT and back in (so the docker group applies).
  2. First start:   cd $APP_DIR && bash devops/scripts/deploy.sh
  3. Add the GitHub secrets (EC2_HOST, EC2_USER, EC2_SSH_KEY) - see README "Deployment".
MSG