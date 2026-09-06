#!/usr/bin/env bash
# Удаляет Docker-развёртывание; секреты и volume удаляются только с --purge.
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

PURGE=0
case "${1:-}" in
    "") ;;
    --purge) PURGE=1 ;;
    -h|--help)
        echo "Использование: ./uninstall.sh [--purge]"
        echo "Без --purge контейнеры удаляются, состояние и секреты сохраняются."
        exit 0
        ;;
    *) echo "Неизвестный аргумент: $1" >&2; exit 2 ;;
esac

if (( PURGE )); then
    echo "Будут удалены контейнеры, Docker volume, .env и Bearer Token."
    read -rp "Продолжить? [y/N] " answer
    [[ "$answer" == [yY]* ]] || { echo "Отменено."; exit 0; }
    docker compose down --volumes --remove-orphans
    rm -f -- .env
    echo "Развёртывание и локальные секреты удалены без возможности восстановления."
else
    docker compose down --remove-orphans
    echo "Контейнеры удалены. .env, Bearer Token и состояние сохранены."
fi
