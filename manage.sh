#!/usr/bin/env bash
# Safe operations for the Docker deployment.
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
source "$ROOT_DIR/scripts/secrets.sh"

usage() {
    cat <<'USAGE'
Usage: ./manage.sh <command>

Commands:
  show          Show credentials, RTSP URLs, and snapshot URLs
  access        Show MQTT credentials and discovered access devices
  status        Show containers and sanitized controller state
  check-streams Actively check every upstream (temporarily starts media)
  logs          Show controller logs without upstream URLs
  logs-media    Show go2rtc/FFmpeg logs (may contain source URLs)
  refresh       Recreate only the controller and refresh cameras/settings
  set-token     Replace the Bearer Token and restart only the controller
  up            Start services
  down          Stop services and preserve state
USAGE
}

COMMAND="${1:-}"
case "$COMMAND" in
    -h|--help|help|"") usage; exit 0 ;;
    show|access|status|check-streams|logs|logs-media|refresh|set-token|up|down) ;;
    *)
        echo "Unknown command: $COMMAND" >&2
        usage
        exit 2
        ;;
esac

[[ -f .env ]] || {
    echo ".env is missing. Run ./install.sh first." >&2
    exit 1
}

case "$COMMAND" in
    show)
        exec docker compose exec -T controller python -m rtkey_gateway show
        ;;
    access)
        exec docker compose exec -T controller python -m rtkey_gateway access-show
        ;;
    status)
        docker compose ps
        docker compose exec -T controller python -m rtkey_gateway status
        ;;
    check-streams)
        exec docker compose exec -T controller \
            python -m rtkey_gateway deep-healthcheck
        ;;
    logs)
        exec docker compose logs -f --tail=200 controller
        ;;
    logs-media)
        echo "Warning: go2rtc/FFmpeg may print temporary upstream URLs." >&2
        echo "Do not publish these logs before reviewing and removing secrets." >&2
        exec docker compose logs -f --tail=200 go2rtc
        ;;
    refresh)
        docker compose up -d --force-recreate --no-deps controller
        echo "Controller recreated; go2rtc and the RTSP server stayed online."
        ;;
    set-token)
        [[ -t 0 ]] || {
            echo "An interactive terminal is required for secure token entry." >&2
            exit 1
        }
        read -rsp "New Bearer Token: " token
        echo
        if ! token="$(normalize_access_token "$token")"; then
            echo "Invalid Bearer Token." >&2
            exit 2
        fi
        write_access_token_secret "$token"
        docker compose up -d --force-recreate --no-deps controller
        echo "Token replaced. go2rtc stayed online without a restart."
        ;;
    up)
        exec docker compose up -d --build
        ;;
    down)
        exec docker compose down
        ;;
esac
