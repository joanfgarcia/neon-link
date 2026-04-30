#!/bin/bash
# Generador de Digest para Auditoría de Neon-Link
# Empaqueta el código fuente limpio ignorando cachés y secretos.

set -e

PROJECT_NAME="neon-link"
VERSION=$(grep version pyproject.toml | head -n 1 | awk -F '"' '{print $2}')
DIGEST_FILE="audit_${PROJECT_NAME}_v${VERSION}_$(date +%Y%m%d).tar.gz"

echo "Preparando Digest para auditoría..."

# Compilar un listado de checksums de los ficheros fuente
find src/ tests/ docs/ -type f -name "*.py" -o -name "*.md" -o -name "*.toml" | sort | xargs sha256sum > audit_checksums.txt

# Empaquetar todo el proyecto limpio (excluyendo secretos y virtualenvs)
tar --exclude=".*" \
    --exclude="__pycache__" \
    --exclude="*.seed" \
    --exclude="*.env" \
    --exclude="*.sqlite" \
    --exclude="node_modules" \
    --exclude="*.tar.gz" \
    -czvf $DIGEST_FILE src/ tests/ docs/ scripts/ pyproject.toml README.md audit_checksums.txt > /dev/null

echo "✅ Auditoría lista: $DIGEST_FILE"
echo "✅ Checksums guardados en: audit_checksums.txt"
