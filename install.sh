#!/usr/bin/env bash
# Fast, repeatable RT Key -> go2rtc deployment with Docker Compose.
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
source "$ROOT_DIR/scripts/secrets.sh"
chmod +x manage.sh uninstall.sh 2>/dev/null || true

read_env() {
    local key="$1"
    [[ -f .env ]] || return 0
    sed -n "s/^${key}=//p" .env | tail -n 1
}

ACCESS_TOKEN="${ACCESS_TOKEN:-$(read_access_token_secret)}"
# One-time migration for installations created before file-backed secrets.
ACCESS_TOKEN="${ACCESS_TOKEN:-$(read_env RTKEY_ACCESS_TOKEN)}"
SERVER_IP="${SERVER_IP:-$(read_env SERVER_IP)}"
RTSP_PORT="${RTSP_PORT:-$(read_env RTSP_PORT)}"
RTSP_PORT="${RTSP_PORT:-8554}"
SNAPSHOT_PORT="${SNAPSHOT_PORT:-$(read_env SNAPSHOT_PORT)}"
SNAPSHOT_PORT="${SNAPSHOT_PORT:-8080}"
SNAPSHOT_WORKERS="${SNAPSHOT_WORKERS:-$(read_env SNAPSHOT_WORKERS)}"
SNAPSHOT_WORKERS="${SNAPSHOT_WORKERS:-2}"
SNAPSHOT_CACHE_SECONDS="${SNAPSHOT_CACHE_SECONDS:-$(read_env SNAPSHOT_CACHE_SECONDS)}"
SNAPSHOT_CACHE_SECONDS="${SNAPSHOT_CACHE_SECONDS:-30}"
RTSP_PROBE_WORKERS="${RTSP_PROBE_WORKERS:-$(read_env RTSP_PROBE_WORKERS)}"
RTSP_PROBE_WORKERS="${RTSP_PROBE_WORKERS:-1}"
ACCESS_CONTROL="${ACCESS_CONTROL:-$(read_env ACCESS_CONTROL)}"
ACCESS_CONTROL="${ACCESS_CONTROL:-off}"
MQTT_HOST="${MQTT_HOST:-$(read_env MQTT_HOST)}"
MQTT_PORT="${MQTT_PORT:-$(read_env MQTT_PORT)}"
MQTT_PORT="${MQTT_PORT:-44444}"
MQTT_USERNAME="${MQTT_USERNAME:-$(read_env MQTT_USERNAME)}"
MQTT_PASSWORD="${MQTT_PASSWORD:-$(read_env MQTT_PASSWORD)}"

usage() {
    cat <<'USAGE'
Usage: ./install.sh [options]

Options:
  --token <TOKEN>        Rostelecom Key Bearer Token
  --server-ip <IP>       Server IP visible to SprutHub
  --rtsp-port <PORT>     Published RTSP port (default: 8554)
  --snapshot-port <PORT> Published HTTP snapshot port (default: 8080)
  --snapshot-workers <N> Maximum concurrent snapshots (default: 2)
  --snapshot-cache <SEC> Reuse a JPEG for this many seconds (default: 30)
  --probe-workers <N>    Concurrent initial stream checks (default: 1)
  --access-control <MODE> off|mqtt (default: off)
  --mqtt-host <HOST>     SprutHub LAN address when MQTT access is enabled
  --mqtt-port <PORT>     SprutHub MQTT port (default: 44444)
  --mqtt-user <USER>     SprutHub MQTT broker username
  --mqtt-password <PASS> SprutHub MQTT broker password
  -h, --help             Show this help

The matching environment variables are also supported.
Docker Engine and the "docker compose" command must already be installed.
USAGE
}

require_value() {
    if (( $# < 2 )) || [[ -z "$2" ]]; then
        echo "$1 requires a non-empty value." >&2
        exit 2
    fi
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --token) require_value "$@"; ACCESS_TOKEN="$2"; shift 2 ;;
        --token=*) ACCESS_TOKEN="${1#*=}"; shift ;;
        --server-ip) require_value "$@"; SERVER_IP="$2"; shift 2 ;;
        --server-ip=*) SERVER_IP="${1#*=}"; shift ;;
        --rtsp-port) require_value "$@"; RTSP_PORT="$2"; shift 2 ;;
        --rtsp-port=*) RTSP_PORT="${1#*=}"; shift ;;
        --snapshot-port) require_value "$@"; SNAPSHOT_PORT="$2"; shift 2 ;;
        --snapshot-port=*) SNAPSHOT_PORT="${1#*=}"; shift ;;
        --snapshot-workers) require_value "$@"; SNAPSHOT_WORKERS="$2"; shift 2 ;;
        --snapshot-workers=*) SNAPSHOT_WORKERS="${1#*=}"; shift ;;
        --snapshot-cache) require_value "$@"; SNAPSHOT_CACHE_SECONDS="$2"; shift 2 ;;
        --snapshot-cache=*) SNAPSHOT_CACHE_SECONDS="${1#*=}"; shift ;;
        --probe-workers) require_value "$@"; RTSP_PROBE_WORKERS="$2"; shift 2 ;;
        --probe-workers=*) RTSP_PROBE_WORKERS="${1#*=}"; shift ;;
        --access-control) require_value "$@"; ACCESS_CONTROL="$2"; shift 2 ;;
        --access-control=*) ACCESS_CONTROL="${1#*=}"; shift ;;
        --mqtt-host) require_value "$@"; MQTT_HOST="$2"; shift 2 ;;
        --mqtt-host=*) MQTT_HOST="${1#*=}"; shift ;;
        --mqtt-port) require_value "$@"; MQTT_PORT="$2"; shift 2 ;;
        --mqtt-port=*) MQTT_PORT="${1#*=}"; shift ;;
        --mqtt-user) require_value "$@"; MQTT_USERNAME="$2"; shift 2 ;;
        --mqtt-user=*) MQTT_USERNAME="${1#*=}"; shift ;;
        --mqtt-password) require_value "$@"; MQTT_PASSWORD="$2"; shift 2 ;;
        --mqtt-password=*) MQTT_PASSWORD="${1#*=}"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
    esac
done

command -v docker >/dev/null 2>&1 || {
    echo "Docker was not found. Install Docker Engine first." >&2
    exit 1
}
docker compose version >/dev/null 2>&1 || {
    echo "The 'docker compose' command was not found. Install the Compose plugin." >&2
    exit 1
}

case "$ACCESS_CONTROL" in
    off|mqtt) ;;
    *) echo "Invalid access control mode: $ACCESS_CONTROL" >&2; exit 2 ;;
esac
[[ "$RTSP_PORT" =~ ^[0-9]+$ ]] && (( RTSP_PORT >= 1 && RTSP_PORT <= 65535 )) || {
    echo "RTSP port must be a number from 1 to 65535." >&2
    exit 2
}
[[ "$SNAPSHOT_PORT" =~ ^[0-9]+$ ]] \
    && (( SNAPSHOT_PORT >= 1 && SNAPSHOT_PORT <= 65535 )) || {
    echo "Snapshot port must be a number from 1 to 65535." >&2
    exit 2
}
[[ "$MQTT_PORT" =~ ^[0-9]+$ ]] && (( MQTT_PORT >= 1 && MQTT_PORT <= 65535 )) || {
    echo "MQTT port must be a number from 1 to 65535." >&2
    exit 2
}

if [[ -z "$ACCESS_TOKEN" ]]; then
    [[ -t 0 ]] || {
        echo "Provide a token with --token or ACCESS_TOKEN." >&2
        exit 1
    }
    echo "Get the Bearer Token in your browser:"
    echo "  https://key.rt.ru/main/pwa/dashboard"
    echo "  F12 -> Network -> barrier request -> Authorization: Bearer ..."
    read -rsp "Paste the Bearer Token: " ACCESS_TOKEN
    echo
fi
if ! ACCESS_TOKEN="$(normalize_access_token "$ACCESS_TOKEN")"; then
    echo "Bearer Token is empty or contains characters that are invalid for a JWT." >&2
    exit 2
fi

random_secret() {
    od -An -N24 -tx1 /dev/urandom | tr -d ' \n'
}

if [[ -z "$SERVER_IP" ]] && command -v ip >/dev/null 2>&1; then
    SERVER_IP="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="src") {print $(i+1); exit}}')"
fi
if [[ -z "$SERVER_IP" ]]; then
    SERVER_IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
fi
[[ -n "$SERVER_IP" ]] || {
    echo "Could not detect the server IP. Specify --server-ip." >&2
    exit 1
}
[[ "$SERVER_IP" =~ ^[A-Za-z0-9._:-]+$ ]] || {
    echo "SERVER_IP contains invalid characters." >&2
    exit 2
}

if [[ "$ACCESS_CONTROL" == mqtt ]]; then
    if [[ -z "$MQTT_HOST" ]]; then
        [[ -t 0 ]] || {
            echo "MQTT_HOST is required when access control is enabled." >&2
            exit 1
        }
        read -rp "SprutHub LAN address: " MQTT_HOST
    fi
    if [[ -z "$MQTT_USERNAME" ]]; then
        [[ -t 0 ]] || {
            echo "MQTT_USERNAME is required when access control is enabled." >&2
            exit 1
        }
        read -rp "SprutHub MQTT username: " MQTT_USERNAME
    fi
    if [[ -z "$MQTT_PASSWORD" ]]; then
        [[ -t 0 ]] || {
            echo "MQTT_PASSWORD is required when access control is enabled." >&2
            exit 1
        }
        read -rsp "SprutHub MQTT password: " MQTT_PASSWORD
        echo
    fi
    [[ "$MQTT_HOST" =~ ^[A-Za-z0-9._:-]+$ ]] || {
        echo "MQTT_HOST contains invalid characters." >&2
        exit 2
    }
    [[ "$MQTT_USERNAME" =~ ^[A-Za-z0-9._-]{1,64}$ ]] || {
        echo "MQTT username contains unsupported characters." >&2
        exit 2
    }
    [[ "$MQTT_PASSWORD" =~ ^[A-Za-z0-9._-]{8,128}$ ]] || {
        echo "MQTT password must be 8-128 safe ASCII characters." >&2
        exit 2
    }
fi

RTSP_USERNAME="$(read_env RTSP_USERNAME)"
RTSP_USERNAME="${RTSP_USERNAME:-spruthub}"
RTSP_PASSWORD="$(read_env RTSP_PASSWORD)"
RTSP_PASSWORD="${RTSP_PASSWORD:-$(random_secret)}"
GO2RTC_API_USERNAME="$(read_env GO2RTC_API_USERNAME)"
GO2RTC_API_USERNAME="${GO2RTC_API_USERNAME:-controller}"
GO2RTC_API_PASSWORD="$(read_env GO2RTC_API_PASSWORD)"
GO2RTC_API_PASSWORD="${GO2RTC_API_PASSWORD:-$(random_secret)}"
RTSP_BIND_IP="$(read_env RTSP_BIND_IP)"
RTSP_BIND_IP="${RTSP_BIND_IP:-0.0.0.0}"
SNAPSHOT_BIND_IP="$(read_env SNAPSHOT_BIND_IP)"
SNAPSHOT_BIND_IP="${SNAPSHOT_BIND_IP:-$RTSP_BIND_IP}"
if [[ "$SNAPSHOT_BIND_IP" == "$RTSP_BIND_IP" && "$SNAPSHOT_PORT" == "$RTSP_PORT" ]]; then
    echo "RTSP and snapshot cannot use the same host port on the same IP." >&2
    exit 2
fi
[[ "$SNAPSHOT_WORKERS" =~ ^[0-9]+$ ]] \
    && (( SNAPSHOT_WORKERS >= 1 && SNAPSHOT_WORKERS <= 16 )) || {
    echo "SNAPSHOT_WORKERS must be a number from 1 to 16." >&2
    exit 2
}
[[ "$SNAPSHOT_CACHE_SECONDS" =~ ^[0-9]+$ ]] \
    && (( SNAPSHOT_CACHE_SECONDS >= 1 && SNAPSHOT_CACHE_SECONDS <= 3600 )) || {
    echo "SNAPSHOT_CACHE_SECONDS must be a number from 1 to 3600." >&2
    exit 2
}
ALLOWED_STREAM_HOST_SUFFIXES="$(read_env ALLOWED_STREAM_HOST_SUFFIXES)"
ALLOWED_STREAM_HOST_SUFFIXES="${ALLOWED_STREAM_HOST_SUFFIXES:-camera.rt.ru}"
HTTP_TIMEOUT_SECONDS="$(read_env HTTP_TIMEOUT_SECONDS)"
HTTP_TIMEOUT_SECONDS="${HTTP_TIMEOUT_SECONDS:-20}"
RTSP_PROBE_TIMEOUT_SECONDS="$(read_env RTSP_PROBE_TIMEOUT_SECONDS)"
RTSP_PROBE_TIMEOUT_SECONDS="${RTSP_PROBE_TIMEOUT_SECONDS:-12}"
[[ "$RTSP_PROBE_WORKERS" =~ ^[0-9]+$ ]] \
    && (( RTSP_PROBE_WORKERS >= 1 && RTSP_PROBE_WORKERS <= 32 )) || {
    echo "RTSP_PROBE_WORKERS must be a number from 1 to 32." >&2
    exit 2
}
REFRESH_MARGIN_SECONDS="$(read_env REFRESH_MARGIN_SECONDS)"
REFRESH_MARGIN_SECONDS="${REFRESH_MARGIN_SECONDS:-900}"
FALLBACK_REFRESH_SECONDS="$(read_env FALLBACK_REFRESH_SECONDS)"
FALLBACK_REFRESH_SECONDS="${FALLBACK_REFRESH_SECONDS:-14400}"
RETRY_MIN_SECONDS="$(read_env RETRY_MIN_SECONDS)"
RETRY_MIN_SECONDS="${RETRY_MIN_SECONDS:-30}"
RETRY_MAX_SECONDS="$(read_env RETRY_MAX_SECONDS)"
RETRY_MAX_SECONDS="${RETRY_MAX_SECONDS:-300}"
RUNTIME_CHECK_SECONDS="$(read_env RUNTIME_CHECK_SECONDS)"
RUNTIME_CHECK_SECONDS="${RUNTIME_CHECK_SECONDS:-60}"
HEALTH_MAX_STALE_SECONDS="$(read_env HEALTH_MAX_STALE_SECONDS)"
HEALTH_MAX_STALE_SECONDS="${HEALTH_MAX_STALE_SECONDS:-21600}"
ACCESS_REFRESH_SECONDS="$(read_env ACCESS_REFRESH_SECONDS)"
ACCESS_REFRESH_SECONDS="${ACCESS_REFRESH_SECONDS:-3600}"
ACCESS_RETRY_SECONDS="$(read_env ACCESS_RETRY_SECONDS)"
ACCESS_RETRY_SECONDS="${ACCESS_RETRY_SECONDS:-60}"
ACCESS_OPEN_COOLDOWN_SECONDS="$(read_env ACCESS_OPEN_COOLDOWN_SECONDS)"
ACCESS_OPEN_COOLDOWN_SECONDS="${ACCESS_OPEN_COOLDOWN_SECONDS:-5}"
MQTT_TOPIC_PREFIX="$(read_env MQTT_TOPIC_PREFIX)"
MQTT_TOPIC_PREFIX="${MQTT_TOPIC_PREFIX:-rtkey}"
MQTT_CLIENT_ID="$(read_env MQTT_CLIENT_ID)"
MQTT_CLIENT_ID="${MQTT_CLIENT_ID:-rtkey-gateway}"
MQTT_KEEPALIVE_SECONDS="$(read_env MQTT_KEEPALIVE_SECONDS)"
MQTT_KEEPALIVE_SECONDS="${MQTT_KEEPALIVE_SECONDS:-60}"
LOG_LEVEL="$(read_env LOG_LEVEL)"
LOG_LEVEL="${LOG_LEVEL:-INFO}"
TIMEZONE="$(read_env TZ)"
TIMEZONE="${TZ:-${TIMEZONE:-Asia/Yekaterinburg}}"

umask 077
write_access_token_secret "$ACCESS_TOKEN"
ENV_TMP=".env.$$"
trap 'rm -f -- "$ENV_TMP"' EXIT
cat > "$ENV_TMP" <<EOF
TZ=$TIMEZONE
SERVER_IP=$SERVER_IP
RTSP_BIND_IP=$RTSP_BIND_IP
RTSP_PORT=$RTSP_PORT
SNAPSHOT_BIND_IP=$SNAPSHOT_BIND_IP
SNAPSHOT_PORT=$SNAPSHOT_PORT
SNAPSHOT_WORKERS=$SNAPSHOT_WORKERS
SNAPSHOT_CACHE_SECONDS=$SNAPSHOT_CACHE_SECONDS
RTSP_USERNAME=$RTSP_USERNAME
RTSP_PASSWORD=$RTSP_PASSWORD
GO2RTC_API_USERNAME=$GO2RTC_API_USERNAME
GO2RTC_API_PASSWORD=$GO2RTC_API_PASSWORD
ALLOWED_STREAM_HOST_SUFFIXES=$ALLOWED_STREAM_HOST_SUFFIXES
HTTP_TIMEOUT_SECONDS=$HTTP_TIMEOUT_SECONDS
RTSP_PROBE_TIMEOUT_SECONDS=$RTSP_PROBE_TIMEOUT_SECONDS
RTSP_PROBE_WORKERS=$RTSP_PROBE_WORKERS
REFRESH_MARGIN_SECONDS=$REFRESH_MARGIN_SECONDS
FALLBACK_REFRESH_SECONDS=$FALLBACK_REFRESH_SECONDS
RETRY_MIN_SECONDS=$RETRY_MIN_SECONDS
RETRY_MAX_SECONDS=$RETRY_MAX_SECONDS
RUNTIME_CHECK_SECONDS=$RUNTIME_CHECK_SECONDS
HEALTH_MAX_STALE_SECONDS=$HEALTH_MAX_STALE_SECONDS
ACCESS_CONTROL=$ACCESS_CONTROL
ACCESS_REFRESH_SECONDS=$ACCESS_REFRESH_SECONDS
ACCESS_RETRY_SECONDS=$ACCESS_RETRY_SECONDS
ACCESS_OPEN_COOLDOWN_SECONDS=$ACCESS_OPEN_COOLDOWN_SECONDS
MQTT_HOST=$MQTT_HOST
MQTT_PORT=$MQTT_PORT
MQTT_USERNAME=$MQTT_USERNAME
MQTT_PASSWORD=$MQTT_PASSWORD
MQTT_TOPIC_PREFIX=$MQTT_TOPIC_PREFIX
MQTT_CLIENT_ID=$MQTT_CLIENT_ID
MQTT_KEEPALIVE_SECONDS=$MQTT_KEEPALIVE_SECONDS
LOG_LEVEL=$LOG_LEVEL
EOF
chmod 600 "$ENV_TMP"
mv -f -- "$ENV_TMP" .env
trap - EXIT

echo "Validating the Docker Compose configuration..."
docker compose config --quiet

echo "Building the controller and starting services..."
docker compose up -d --build --force-recreate go2rtc
docker compose up -d --build --force-recreate --no-deps controller

echo "Waiting for the first verified camera list..."
OUTPUT=""
for ((_attempt = 1; _attempt <= 90; _attempt++)); do
    if OUTPUT="$(docker compose exec -T controller python -m rtkey_gateway show 2>/dev/null)"; then
        printf '\n%s\n' "$OUTPUT"
        if [[ "$ACCESS_CONTROL" == mqtt ]]; then
            echo "Waiting for the access device catalog..."
            ACCESS_OUTPUT=""
            for ((_access_attempt = 1; _access_attempt <= 30; _access_attempt++)); do
                if ACCESS_OUTPUT="$(docker compose exec -T controller python -m rtkey_gateway access-show 2>/dev/null)"; then
                    printf '\n%s\n' "$ACCESS_OUTPUT"
                    echo "Import spruthub/rtkey_access_v2.json into the SprutHub MQTT catalog."
                    echo "Then restart the SprutHub MQTT controller to discover retained devices."
                    echo "Management: ./manage.sh status | show | access | logs | set-token"
                    exit 0
                fi
                sleep 2
            done
            echo "Cameras are ready, but access devices were not discovered within 60 seconds." >&2
            echo "Check: ./manage.sh status && ./manage.sh logs" >&2
            exit 1
        fi
        echo "Management: ./manage.sh status | show | access | logs | set-token"
        exit 0
    fi
    sleep 2
done

echo "Containers are running, but cameras were not verified within 180 seconds." >&2
echo "Check: ./manage.sh status && ./manage.sh logs" >&2
docker compose ps
exit 1
