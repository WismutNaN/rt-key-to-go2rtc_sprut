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
  access-templates
                Export one SprutHub template containing all access buttons
  status        Show containers and sanitized controller state
  media-status  Show one-time CPU, memory, and process counters
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
    show|access|access-templates|status|media-status|check-streams|logs|logs-media|refresh|set-token|up|down) ;;
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
    access-templates)
        command -v tar >/dev/null 2>&1 || {
            echo "The tar utility is required to export SprutHub templates." >&2
            exit 1
        }
        umask 077
        generated_root="$ROOT_DIR/generated"
        if ! mkdir -p -- "$generated_root"; then
            echo "Could not create the template output directory." >&2
            exit 1
        fi
        if ! output_dir="$(
            mktemp -d "$generated_root/spruthub-access-$(date -u +%Y%m%d-%H%M%S)-XXXXXX"
        )"; then
            echo "Could not create a unique template output directory." >&2
            exit 1
        fi
        if ! docker compose exec -T controller \
            python -m rtkey_gateway export-access-templates \
            | tar -xf - -C "$output_dir"; then
            echo "Template export failed. Partial output was left at:" >&2
            echo "$output_dir" >&2
            exit 1
        fi
        mapfile -t template_files < <(
            find "$output_dir" -maxdepth 1 -type f -name '*.json' -print | sort
        )
        if (( ${#template_files[@]} != 1 )); then
            echo "Template export must return exactly one JSON file." >&2
            exit 1
        fi
        echo "SprutHub access template created:"
        printf '%s\n' "${template_files[@]}"
        echo
        echo "Import this JSON file into the SprutHub MQTT catalog."
        echo "It contains one named button for every Rostelecom access place."
        ;;
    status)
        docker compose ps
        docker compose exec -T controller python -m rtkey_gateway status
        ;;
    media-status)
        mapfile -t container_ids < <(docker compose ps -q go2rtc controller)
        if (( ${#container_ids[@]} == 0 )); then
            echo "Media services are not running." >&2
            exit 1
        fi
        docker stats --no-stream \
            --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.PIDs}}' \
            "${container_ids[@]}"
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
