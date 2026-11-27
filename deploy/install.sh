#!/usr/bin/env bash
# One-time setup on a fresh Raspberry Pi OS Lite (64-bit). Run from the monpitor folder:
#   bash deploy/install.sh
set -euo pipefail
DIR="$(cd "$(dirname "$0")/.." && pwd)"
USER_NAME="$(id -un)"

echo "== Packages"
sudo apt-get update
sudo apt-get install -y python3-venv python3-dev git openssh-client mpv openssl kbd console-setup

echo "== Python environment"
python3 -m venv "$DIR/.venv"
"$DIR/.venv/bin/pip" install --upgrade pip
"$DIR/.venv/bin/pip" install "aiohttp>=3.9"
# Cast libraries can fail to build on 32-bit Pi OS; the log display works without them.
"$DIR/.venv/bin/pip" install -r "$DIR/requirements.txt" \
  || echo "WARNING: aiortc/av did not install, so screen casting is off. The log display still works."

echo "== Config"
[ -f "$DIR/monpitor.toml" ] || cp "$DIR/monpitor.example.toml" "$DIR/monpitor.toml"

echo "== ssh key (add the .pub to each machine's ~/.ssh/authorized_keys and as a read-only deploy key on overnight-runs)"
[ -f ~/.ssh/id_ed25519 ] || ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519 -C "monpitor"
cat ~/.ssh/id_ed25519.pub

echo "== Self-signed certificate for the cast page (browsers need HTTPS for screen capture)"
mkdir -p "$DIR/certs"
if [ ! -f "$DIR/certs/monpitor.crt" ]; then
  openssl req -x509 -newkey rsa:2048 -nodes -days 3650 \
    -keyout "$DIR/certs/monpitor.key" -out "$DIR/certs/monpitor.crt" \
    -subj "/CN=$(hostname).local" -addext "subjectAltName=DNS:$(hostname).local,DNS:$(hostname)"
fi

echo "== Service"
sed -e "s|@DIR@|$DIR|g" -e "s|@USER@|$USER_NAME|g" "$DIR/deploy/monpitor.service" \
  | sudo tee /etc/systemd/system/monpitor.service >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable monpitor.service

echo
echo "Next: edit $DIR/monpitor.toml (ssh addresses), add the key above where it says,"
echo "then: sudo systemctl start monpitor   (logs: journalctl -u monpitor -f)"
