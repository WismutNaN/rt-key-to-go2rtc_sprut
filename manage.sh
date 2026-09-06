#!/usr/bin/env bash
# Безопасные операции с Docker-развёртыванием.
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
source "$ROOT_DIR/scripts/secrets.sh"

usage() {
    cat <<'USAGE'
Использование: ./manage.sh <команда>

Команды:
  show         показать логин, пароль и RTSP-ссылки всех камер
  status       показать контейнеры и безопасный статус controller
  logs         безопасные логи controller без upstream URL
  logs-media   диагностические логи go2rtc/FFmpeg (могут содержать source)
  refresh      пересоздать только controller и обновить камеры/настройки
  set-token    заменить Bearer Token и перезапустить только controller
  up           запустить сервисы
  down         остановить сервисы, сохранив состояние
USAGE
}

COMMAND="${1:-}"
case "$COMMAND" in
    -h|--help|help|"") usage; exit 0 ;;
    show|status|logs|logs-media|refresh|set-token|up|down) ;;
    *)
        echo "Неизвестная команда: $COMMAND" >&2
        usage
        exit 2
        ;;
esac

[[ -f .env ]] || {
    echo "Файл .env отсутствует. Сначала выполните ./install.sh." >&2
    exit 1
}

case "$COMMAND" in
    show)
        exec docker compose exec -T controller python -m rtkey_gateway show
        ;;
    status)
        docker compose ps
        docker compose exec -T controller python -m rtkey_gateway status
        ;;
    logs)
        exec docker compose logs -f --tail=200 controller
        ;;
    logs-media)
        echo "Внимание: go2rtc/FFmpeg может вывести временный upstream URL." >&2
        echo "Не публикуйте эти логи без проверки и удаления секретов." >&2
        exec docker compose logs -f --tail=200 go2rtc
        ;;
    refresh)
        docker compose up -d --force-recreate --no-deps controller
        echo "Controller пересоздан; go2rtc и RTSP-сервер не останавливались."
        ;;
    set-token)
        [[ -t 0 ]] || {
            echo "Для безопасного ввода токена нужен интерактивный терминал." >&2
            exit 1
        }
        read -rsp "Новый Bearer Token: " token
        echo
        if ! token="$(normalize_access_token "$token")"; then
            echo "Некорректный Bearer Token." >&2
            exit 2
        fi
        write_access_token_secret "$token"
        docker compose up -d --force-recreate --no-deps controller
        echo "Токен заменён. go2rtc продолжал работать без перезапуска."
        ;;
    up)
        exec docker compose up -d --build
        ;;
    down)
        exec docker compose down
        ;;
esac
