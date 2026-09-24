#!/bin/bash
# Build locally, ship to the server, migrate, restart. Idempotent.
#   deploy/deploy.sh            (uses SSH host alias below)
set -euo pipefail
HOST=${HOST:-root@185.8.213.139}
KEY=${KEY:-$HOME/.ssh/uzbridge_deploy}
SSH=(ssh -i "$KEY" -o IdentitiesOnly=yes "$HOST")
ROOT=$(cd "$(dirname "$0")/.." && pwd)

# The dashboard offers the amoCRM widget archive for download.
(cd "$ROOT/widget" && uv run --quiet --with pillow python build.py "${PUBLIC_API:-https://uzbridge.shokhsmee.uz}" >/dev/null)
cp "$ROOT/widget/dist/uzbridge-widget.zip" "$ROOT/frontend/public/uzbridge-widget.zip"
# ...and the Odoo addon (Community + Enterprise).
(cd "$ROOT/odoo_addons" && rm -f "$ROOT/frontend/public/uzbridge-odoo.zip" && zip -qr "$ROOT/frontend/public/uzbridge-odoo.zip" uzbridge uzbridge_pos -x '*/__pycache__/*' '*.pyc')
(cd "$ROOT/frontend" && npm run build >/dev/null)
rsync -az --delete -e "ssh -i $KEY -o IdentitiesOnly=yes" \
    --exclude .venv --exclude .env --exclude __pycache__ --exclude staticfiles --exclude '.pytest_cache' --exclude '.ruff_cache' \
    "$ROOT/backend/" "$HOST:/opt/uzbridge/backend/"
rsync -az --delete -e "ssh -i $KEY -o IdentitiesOnly=yes" "$ROOT/frontend/dist/" "$HOST:/opt/uzbridge/frontend/"
rsync -az -e "ssh -i $KEY -o IdentitiesOnly=yes" "$ROOT/deploy/" "$HOST:/opt/uzbridge/deploy/"

"${SSH[@]}" 'set -e
chown -R uzbridge:uzbridge /opt/uzbridge/backend
cd /opt/uzbridge/backend
sudo -u uzbridge /opt/uzbridge/venv/bin/pip install -q -r requirements.txt
sudo -u uzbridge /opt/uzbridge/venv/bin/python manage.py migrate --noinput
sudo -u uzbridge /opt/uzbridge/venv/bin/python manage.py collectstatic --noinput -v0
# nginx site: install the repo copy when it changed, only if it passes nginx -t.
sed "s/__DOMAIN__/uzbridge.shokhsmee.uz/g" /opt/uzbridge/deploy/nginx-https.conf > /tmp/uzbridge-https.conf
if ! cmp -s /tmp/uzbridge-https.conf /etc/nginx/sites-available/uzbridge-https.conf; then
  cp /etc/nginx/sites-available/uzbridge-https.conf /etc/nginx/sites-available/uzbridge-https.conf.bak
  cp /tmp/uzbridge-https.conf /etc/nginx/sites-available/uzbridge-https.conf
  if nginx -t 2>/dev/null; then systemctl reload nginx; else
    cp /etc/nginx/sites-available/uzbridge-https.conf.bak /etc/nginx/sites-available/uzbridge-https.conf
    echo "nginx config rejected; kept the old one" >&2
  fi
fi
systemctl restart uzbridge-web uzbridge-worker
systemctl is-active uzbridge-web uzbridge-worker'
