#!/bin/bash
# Script de arranque seguro para Neon-Link

# Obligamos a que el bind sea estrictamente local (127.0.0.1) para evitar
# problemas de seguridad con las auditorías al ir sin HTTPS.
HOST="127.0.0.1"
PORT="8770"

echo "Iniciando Neon-Link Daemon (Polling)..."
/home/joan/.local/bin/uv run python src/neon_link/cli.py &

echo "Iniciando Neon-Link API en $HOST:$PORT..."
/home/joan/.local/bin/uv run uvicorn neon_link.api.server:app --host $HOST --port $PORT --reload
