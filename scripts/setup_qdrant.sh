#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="fossick-qdrant"
IMAGE="qdrant/qdrant:latest"
VOLUME_NAME="qdrant_data"
PORT=6333

# Check if container already exists
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo "Qdrant container '${CONTAINER_NAME}' is already running."
    else
        echo "Starting existing Qdrant container '${CONTAINER_NAME}'..."
        docker start "${CONTAINER_NAME}"
        echo "Qdrant started on port ${PORT}."
    fi
    exit 0
fi

echo "Creating and starting Qdrant container '${CONTAINER_NAME}'..."
docker run -d \
    --name "${CONTAINER_NAME}" \
    --restart unless-stopped \
    --memory=512m \
    -p "${PORT}:6333" \
    -v "${VOLUME_NAME}:/qdrant/storage" \
    "${IMAGE}"

echo "Qdrant is running on http://localhost:${PORT}"
echo "Dashboard: http://localhost:${PORT}/dashboard"
