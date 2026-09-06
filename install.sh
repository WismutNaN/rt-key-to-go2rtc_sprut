#!/usr/bin/env bash
# Быстрый и повторяемый запуск RT Key -> go2rtc через Docker Compose.
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
RTSP_PROBE_WORKERS="${RTSP_PROBE_WORKERS:-$(read_env RTSP_PROBE_WORKERS)}"
RTSP_PROBE_WORKERS="${RTSP_PROBE_WORKERS:-1}"
AUDIO_MODE="${AUDIO_MODE:-$(read_env AUDIO_MODE)}"
AUDIO_MODE="${AUDIO_MODE:-pcma}"
VIDEO_MODE="${VIDEO_MODE:-$(read_env VIDEO_MODE)}"
VIDEO_MODE="${VIDEO_MODE:-h264}"
VIDEO_FPS="${VIDEO_FPS:-$(read_env VIDEO_FPS)}"
VIDEO_FPS="${VIDEO_FPS:-30}"
VIDEO_RESOLUTIONS="${VIDEO_RESOLUTIONS:-$(read_env VIDEO_RESOLUTIONS)}"
VIDEO_RESOLUTIONS="${VIDEO_RESOLUTIONS:-source,1280x720,640x360}"

usage() {
    cat <<'USAGE'
Использование: ./install.sh [опции]

Опции:
  --token <TOKEN>       Bearer Token Ростелеком Ключ
  --server-ip <IP>      IP сервера, который увидит SprutHub
  --rtsp-port <PORT>    внешний RTSP-порт (по умолчанию 8554)
  --snapshot-port <PORT> внешний HTTP snapshot-порт (по умолчанию 8080)
  --snapshot-workers <N> не более N одновременных снимков (по умолчанию 2)
  --probe-workers <N>  параллельные первичные проверки (по умолчанию 1)
  --audio <MODE>        copy|aac|pcma|pcmu|none (по умолчанию pcma)
  --video <MODE>        h264|copy (по умолчанию стабильный h264)
  --fps <N>             частота стабильных H.264-вариантов, 1..60
  --resolutions <LIST>  source,1280x720,640x360 (от одного до четырёх)
  -h, --help            показать справку

Также поддерживаются ACCESS_TOKEN, SERVER_IP, RTSP_PORT, SNAPSHOT_PORT,
AUDIO_MODE, VIDEO_MODE и VIDEO_RESOLUTIONS.
Docker Engine и команда "docker compose" должны быть установлены заранее.
USAGE
}

require_value() {
    if (( $# < 2 )) || [[ -z "$2" ]]; then
        echo "Для $1 требуется непустое значение." >&2
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
        --probe-workers) require_value "$@"; RTSP_PROBE_WORKERS="$2"; shift 2 ;;
        --probe-workers=*) RTSP_PROBE_WORKERS="${1#*=}"; shift ;;
        --audio) require_value "$@"; AUDIO_MODE="$2"; shift 2 ;;
        --audio=*) AUDIO_MODE="${1#*=}"; shift ;;
        --video) require_value "$@"; VIDEO_MODE="$2"; shift 2 ;;
        --video=*) VIDEO_MODE="${1#*=}"; shift ;;
        --fps) require_value "$@"; VIDEO_FPS="$2"; shift 2 ;;
        --fps=*) VIDEO_FPS="${1#*=}"; shift ;;
        --resolutions) require_value "$@"; VIDEO_RESOLUTIONS="$2"; shift 2 ;;
        --resolutions=*) VIDEO_RESOLUTIONS="${1#*=}"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Неизвестный аргумент: $1" >&2; usage; exit 2 ;;
    esac
done

command -v docker >/dev/null 2>&1 || {
    echo "Docker не найден. Сначала установите Docker Engine." >&2
    exit 1
}
docker compose version >/dev/null 2>&1 || {
    echo "Не найдена команда 'docker compose'. Установите Compose plugin." >&2
    exit 1
}

case "$AUDIO_MODE" in
    copy|aac|pcma|pcmu|none) ;;
    *) echo "Неверный audio mode: $AUDIO_MODE" >&2; exit 2 ;;
esac
case "$VIDEO_MODE" in
    h264|copy) ;;
    *) echo "Неверный video mode: $VIDEO_MODE" >&2; exit 2 ;;
esac
[[ "$VIDEO_RESOLUTIONS" =~ ^source(,[0-9]+x[0-9]+){0,3}$ ]] || {
    echo "Разрешения: source и до трёх значений WIDTHxHEIGHT через запятую." >&2
    exit 2
}
IFS=',' read -r -a RESOLUTION_ITEMS <<< "$VIDEO_RESOLUTIONS"
declare -A SEEN_RESOLUTIONS=()
for RESOLUTION_ITEM in "${RESOLUTION_ITEMS[@]}"; do
    [[ -z "${SEEN_RESOLUTIONS[$RESOLUTION_ITEM]:-}" ]] || {
        echo "Разрешения не должны повторяться." >&2
        exit 2
    }
    SEEN_RESOLUTIONS[$RESOLUTION_ITEM]=1
    [[ "$RESOLUTION_ITEM" == source ]] && continue
    WIDTH="${RESOLUTION_ITEM%x*}"
    HEIGHT="${RESOLUTION_ITEM#*x}"
    (( WIDTH >= 160 && WIDTH <= 3840 && HEIGHT >= 90 && HEIGHT <= 2160 \
        && WIDTH % 2 == 0 && HEIGHT % 2 == 0 )) || {
        echo "Разрешение $RESOLUTION_ITEM должно быть чётным и в диапазоне 160x90..3840x2160." >&2
        exit 2
    }
done
[[ "$RTSP_PORT" =~ ^[0-9]+$ ]] && (( RTSP_PORT >= 1 && RTSP_PORT <= 65535 )) || {
    echo "RTSP-порт должен быть числом от 1 до 65535." >&2
    exit 2
}
[[ "$SNAPSHOT_PORT" =~ ^[0-9]+$ ]] \
    && (( SNAPSHOT_PORT >= 1 && SNAPSHOT_PORT <= 65535 )) || {
    echo "Snapshot-порт должен быть числом от 1 до 65535." >&2
    exit 2
}

if [[ -z "$ACCESS_TOKEN" ]]; then
    [[ -t 0 ]] || {
        echo "Передайте токен через --token или ACCESS_TOKEN." >&2
        exit 1
    }
    echo "Получите Bearer Token в браузере:"
    echo "  https://key.rt.ru/main/pwa/dashboard"
    echo "  F12 -> Network -> запрос barrier -> Authorization: Bearer ..."
    read -rsp "Вставьте Bearer Token: " ACCESS_TOKEN
    echo
fi
if ! ACCESS_TOKEN="$(normalize_access_token "$ACCESS_TOKEN")"; then
    echo "Bearer Token пуст или содержит символы, недопустимые для JWT." >&2
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
    echo "Не удалось определить IP сервера. Укажите --server-ip." >&2
    exit 1
}
[[ "$SERVER_IP" =~ ^[A-Za-z0-9._:-]+$ ]] || {
    echo "SERVER_IP содержит недопустимые символы." >&2
    exit 2
}

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
    echo "RTSP и snapshot не могут использовать один host-порт на одном IP." >&2
    exit 2
fi
[[ "$SNAPSHOT_WORKERS" =~ ^[0-9]+$ ]] \
    && (( SNAPSHOT_WORKERS >= 1 && SNAPSHOT_WORKERS <= 16 )) || {
    echo "SNAPSHOT_WORKERS должен быть числом от 1 до 16." >&2
    exit 2
}
AUDIO_OVERRIDES_JSON="$(read_env AUDIO_OVERRIDES_JSON)"
if [[ -z "$AUDIO_OVERRIDES_JSON" ]]; then
    AUDIO_OVERRIDES_JSON='{}'
fi
[[ "$VIDEO_FPS" =~ ^[0-9]+$ ]] && (( VIDEO_FPS >= 1 && VIDEO_FPS <= 60 )) || {
    echo "VIDEO_FPS должен быть числом от 1 до 60." >&2
    exit 2
}
VIDEO_OVERRIDES_JSON="$(read_env VIDEO_OVERRIDES_JSON)"
if [[ -z "$VIDEO_OVERRIDES_JSON" ]]; then
    VIDEO_OVERRIDES_JSON='{}'
fi
ALLOWED_STREAM_HOST_SUFFIXES="$(read_env ALLOWED_STREAM_HOST_SUFFIXES)"
ALLOWED_STREAM_HOST_SUFFIXES="${ALLOWED_STREAM_HOST_SUFFIXES:-camera.rt.ru}"
HTTP_TIMEOUT_SECONDS="$(read_env HTTP_TIMEOUT_SECONDS)"
HTTP_TIMEOUT_SECONDS="${HTTP_TIMEOUT_SECONDS:-20}"
RTSP_PROBE_TIMEOUT_SECONDS="$(read_env RTSP_PROBE_TIMEOUT_SECONDS)"
RTSP_PROBE_TIMEOUT_SECONDS="${RTSP_PROBE_TIMEOUT_SECONDS:-12}"
[[ "$RTSP_PROBE_WORKERS" =~ ^[0-9]+$ ]] \
    && (( RTSP_PROBE_WORKERS >= 1 && RTSP_PROBE_WORKERS <= 32 )) || {
    echo "RTSP_PROBE_WORKERS должен быть числом от 1 до 32." >&2
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
RTSP_USERNAME=$RTSP_USERNAME
RTSP_PASSWORD=$RTSP_PASSWORD
GO2RTC_API_USERNAME=$GO2RTC_API_USERNAME
GO2RTC_API_PASSWORD=$GO2RTC_API_PASSWORD
VIDEO_MODE=$VIDEO_MODE
VIDEO_FPS=$VIDEO_FPS
VIDEO_RESOLUTIONS=$VIDEO_RESOLUTIONS
VIDEO_OVERRIDES_JSON=$VIDEO_OVERRIDES_JSON
AUDIO_MODE=$AUDIO_MODE
AUDIO_OVERRIDES_JSON=$AUDIO_OVERRIDES_JSON
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
LOG_LEVEL=$LOG_LEVEL
EOF
chmod 600 "$ENV_TMP"
mv -f -- "$ENV_TMP" .env
trap - EXIT

echo "Проверяю конфигурацию Docker Compose..."
docker compose config --quiet

echo "Собираю controller и запускаю сервисы..."
docker compose up -d --build go2rtc
docker compose up -d --build --force-recreate --no-deps controller

echo "Ожидаю первый проверенный список камер..."
OUTPUT=""
for ((_attempt = 1; _attempt <= 90; _attempt++)); do
    if OUTPUT="$(docker compose exec -T controller python -m rtkey_gateway show 2>/dev/null)"; then
        printf '\n%s\n' "$OUTPUT"
        echo "Управление: ./manage.sh status | show | logs | set-token"
        exit 0
    fi
    sleep 2
done

echo "Контейнеры запущены, но камеры не прошли проверку за 180 секунд." >&2
echo "Проверьте: ./manage.sh status && ./manage.sh logs" >&2
docker compose ps
exit 1
