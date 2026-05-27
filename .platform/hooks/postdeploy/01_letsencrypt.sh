#!/usr/bin/env bash
# -----------------------------------------------------------------------------
# Issue and install a Let's Encrypt certificate for the custom domain on this
# single-instance EB environment, then drop a top-level nginx server block
# (/etc/nginx/conf.d/https.conf) that proxies HTTPS traffic to gunicorn.
#
# Runs after every deploy:
#   * First deploy        : installs certbot, requests a cert, configures nginx
#   * Subsequent deploys  : reuses existing cert, just rewrites nginx config
#                           and reloads
#
# Cert auto-renewal is handled by /etc/cron.d/certbot-renew, written below.
# -----------------------------------------------------------------------------
set -euo pipefail

DOMAIN_PRIMARY="www.sk-bukal.online"
DOMAIN_APEX="sk-bukal.online"
LE_EMAIL="ceaneazucena@gmail.com"
LIVE_DIR="/etc/letsencrypt/live/${DOMAIN_PRIMARY}"
HTTPS_CONF="/etc/nginx/conf.d/https.conf"
CERTBOT_BIN="/usr/local/bin/certbot"

log() { echo "[letsencrypt-hook] $*"; }

# 1. Install certbot via pip if it isn't on the box yet.
if ! command -v "${CERTBOT_BIN}" >/dev/null 2>&1; then
    log "Installing certbot via pip"
    dnf install -y python3-pip >/dev/null
    python3 -m pip install --quiet --upgrade pip
    python3 -m pip install --quiet certbot
fi

# 2. Request the cert if we don't already have it.
if [ ! -f "${LIVE_DIR}/fullchain.pem" ]; then
    log "Requesting Let's Encrypt cert for ${DOMAIN_PRIMARY} / ${DOMAIN_APEX}"
    # certbot --standalone needs port 80 free, so stop nginx briefly.
    systemctl stop nginx || true
    "${CERTBOT_BIN}" certonly --standalone \
        -d "${DOMAIN_PRIMARY}" -d "${DOMAIN_APEX}" \
        --non-interactive --agree-tos --no-eff-email \
        --email "${LE_EMAIL}" \
        --keep-until-expiring
    systemctl start nginx
else
    log "Cert already exists at ${LIVE_DIR}, skipping issuance"
fi

# 3. Drop the HTTPS server block. Top-level /etc/nginx/conf.d/ is preserved
#    between deploys, but we rewrite it every time so config changes here
#    take effect on the next push.
cat > "${HTTPS_CONF}" << EOF
# Managed by .platform/hooks/postdeploy/01_letsencrypt.sh — do not edit by hand.
server {
    listen       443 ssl;
    listen       [::]:443 ssl;
    http2        on;
    server_name  ${DOMAIN_PRIMARY} ${DOMAIN_APEX};

    ssl_certificate     ${LIVE_DIR}/fullchain.pem;
    ssl_certificate_key ${LIVE_DIR}/privkey.pem;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache   shared:SSL:10m;
    ssl_session_timeout 1d;

    client_max_body_size 25M;

    location /static/ {
        alias /var/app/current/static/;
    }

    location / {
        proxy_pass          http://127.0.0.1:8000;
        proxy_http_version  1.1;
        proxy_set_header    Connection         "";
        proxy_set_header    Host               \$host;
        proxy_set_header    X-Real-IP          \$remote_addr;
        proxy_set_header    X-Forwarded-For    \$proxy_add_x_forwarded_for;
        proxy_set_header    X-Forwarded-Proto  https;
    }
}

# Force HTTP traffic over to HTTPS so the green padlock is the default
# experience. Keeps the ACME challenge path open in case certbot ever
# falls back to webroot validation.
server {
    listen       80;
    listen       [::]:80;
    server_name  ${DOMAIN_PRIMARY} ${DOMAIN_APEX};

    location /.well-known/acme-challenge/ {
        root /var/www/letsencrypt;
    }

    location / {
        return 301 https://${DOMAIN_PRIMARY}\$request_uri;
    }
}
EOF

mkdir -p /var/www/letsencrypt

# 4. Validate config and reload nginx.
if nginx -t; then
    log "Reloading nginx with HTTPS config"
    systemctl reload nginx
else
    log "nginx -t failed — leaving the previous config in place"
    exit 1
fi

# 5. Drop a cron job that renews the cert (certbot only renews if the
#    cert is within 30 days of expiry). Stops/starts nginx around the
#    renewal so the standalone authenticator can bind to port 80.
cat > /etc/cron.d/certbot-renew << 'CRON'
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin
17 3 * * * root /usr/local/bin/certbot renew --quiet \
  --pre-hook  "systemctl stop nginx" \
  --post-hook "systemctl start nginx" \
  >> /var/log/letsencrypt-renew.log 2>&1
CRON
chmod 644 /etc/cron.d/certbot-renew

log "HTTPS setup complete"
