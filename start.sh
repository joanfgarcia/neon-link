#!/bin/bash
# Script de arranque seguro para Neon-Link

# Obligamos a que el bind sea estrictamente local (127.0.0.1) para evitar
# problemas de seguridad con las auditorías al ir sin HTTPS.
HOST="127.0.0.1"
PORT="8770"
# uv del PATH; bajo systemd (PATH mínimo) cae a la instalación por defecto del usuario.
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"

echo "Iniciando Neon-Link Daemon (Polling)..."
"$UV" run python src/neon_link/cli.py &

echo "Iniciando Neon-Link API en $HOST:$PORT..."
"$UV" run uvicorn neon_link.api.server:app --host $HOST --port $PORT --reload
