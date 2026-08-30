#!/usr/bin/env bash
set -euo pipefail

# JobFinder Deploy Script
# Usage: ./deploy.sh [build|up|down|logs|status|update]

ACTION="${1:-up}"
COMPOSE_FILE="docker-compose.yml"

case "$ACTION" in
  build)
    echo "🔨 Building image..."
    docker compose -f "$COMPOSE_FILE" build --no-cache
    echo "✅ Build complete."
    ;;

  up)
    echo "🚀 Starting JobFinder..."
    docker compose -f "$COMPOSE_FILE" up -d --build
    echo "✅ JobFinder is running."
    echo "📋 Logs: ./deploy.sh logs"
    ;;

  down)
    echo "🛑 Stopping JobFinder..."
    docker compose -f "$COMPOSE_FILE" down
    echo "✅ Stopped."
    ;;

  logs)
    docker compose -f "$COMPOSE_FILE" logs -f --tail=50
    ;;

  status)
    docker compose -f "$COMPOSE_FILE" ps
    ;;

  update)
    echo "🔄 Updating JobFinder..."
    git pull
    docker compose -f "$COMPOSE_FILE" up -d --build
    echo "✅ Updated and running."
    ;;

  *)
    echo "Usage: $0 {build|up|down|logs|status|update}"
    exit 1
    ;;
esac
