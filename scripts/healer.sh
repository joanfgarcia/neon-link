#!/bin/bash
# Neon-Link Healer Watchdog
# Pings the /health endpoint. If it fails, restarts the systemd service.

ENDPOINT="http://127.0.0.1:8770/health"
SERVICE="neon-link.service"

RESPONSE=$(curl -s -o /dev/null -w "%{http_code}" "$ENDPOINT" --max-time 5)

if [ "$RESPONSE" != "200" ]; then
    echo "$(date) - [HEALER] Health check failed (HTTP $RESPONSE). Restarting $SERVICE..." >> /home/joan/Documents/IA/neon-link/neon_link.log
    systemctl --user restart "$SERVICE"
else
    echo "$(date) - [HEALER] System healthy." >> /dev/null
fi
