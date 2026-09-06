#!/usr/bin/env bash
# Remove the Docker deployment; delete secrets and volume only with --purge.
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
source "$ROOT_DIR/scripts/secrets.sh"

PURGE=0
case "${1:-}" in
    "") ;;
    --purge) PURGE=1 ;;
    -h|--help)
        echo "Usage: ./uninstall.sh [--purge]"
        echo "Without --purge, containers are removed while state and secrets are kept."
        exit 0
        ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
esac

if (( PURGE )); then
    echo "Containers, the Docker volume, .env, and the Bearer Token will be deleted."
    read -rp "Continue? [y/N] " answer
    [[ "$answer" == [yY]* ]] || { echo "Cancelled."; exit 0; }
    docker compose down --volumes --remove-orphans
    rm -f -- .env "$ACCESS_TOKEN_FILE"
    rmdir -- "$SECRET_DIR" 2>/dev/null || true
    echo "Deployment and local secrets were permanently deleted."
else
    docker compose down --remove-orphans
    echo "Containers removed. .env, the Bearer Token, and state were preserved."
fi
