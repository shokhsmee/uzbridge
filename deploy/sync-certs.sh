#!/bin/bash
# Make sure the "uzbridge" certificate covers app, api and every company
# subdomain, then publish the covered hosts for the app's /auth/host-ready.
# Runs as root from uzbridge-certs.service (triggered by the app after signup).
set -euo pipefail

APP=/opt/uzbridge
STATE=/var/lib/uzbridge
LIVE=/etc/letsencrypt/live/uzbridge/cert.pem

wanted=$(sudo -u uzbridge "$APP/venv/bin/python" "$APP/backend/manage.py" uzbridge_hosts | sort -u)

covered() {
    [ -f "$LIVE" ] || return 0
    openssl x509 -in "$LIVE" -noout -ext subjectAltName | grep -o 'DNS:[^,]*' | sed 's/DNS://' | sort -u
}

missing=$(comm -23 <(echo "$wanted") <(covered))
if [ -n "$missing" ]; then
    args=()
    for h in $wanted; do args+=(-d "$h"); done
    certbot certonly --webroot -w /var/www/uzbridge-acme --cert-name uzbridge --expand \
        --non-interactive --keep-until-expiring "${args[@]}"
    if [ ! -e /etc/nginx/sites-enabled/uzbridge-https.conf ]; then
        ln -s /etc/nginx/sites-available/uzbridge-https.conf /etc/nginx/sites-enabled/uzbridge-https.conf
    fi
    nginx -t && systemctl reload nginx
fi

covered > "$STATE/hosts-ready.tmp"
chown uzbridge:uzbridge "$STATE/hosts-ready.tmp"
mv "$STATE/hosts-ready.tmp" "$STATE/hosts-ready"
