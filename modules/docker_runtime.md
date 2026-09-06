# Модуль: Docker runtime

**Ответственность**: описывает воспроизводимый запуск controller и go2rtc на целевом Linux-сервере.
**Расположение**: `compose.yaml`, `Dockerfile`, `go2rtc/go2rtc.yaml`

## Публичный интерфейс

| Символ | Тип | Описание |
|---|---|---|
| `controller` | Compose service | Python-сервис обнаружения и refresh |
| `go2rtc` | Compose service | Закреплённый media gateway 1.9.14 |
| `gateway-state` | named volume | Mapping и last-known-good |
| `rtkey-net` | network | Внутренняя связь controller → API go2rtc |

## Зависимости

| Модуль | Что использует |
|---|---|
| `quick_start` | Созданные environment/secrets |
| `healthcheck` | Команды проверки контейнеров |
| официальный image go2rtc | FFmpeg и RTSP/API server |

## Инварианты

- Используется `alexxit/go2rtc:1.9.14`, не `latest`.
- Controller собирается из `python:3.12.14-alpine3.24`, а не плавающего minor-тега.
- Порт `1984` отсутствует в `ports`.
- Публикуются `${RTSP_PORT:-8554}:8554/tcp` и узкий Basic-auth snapshot
  `${SNAPSHOT_PORT:-8080}:8080/tcp`; API `1984` не публикуется.
- Privileged, host network и GPU не требуются. По умолчанию H.264 передаётся без
  декодирования; программная нормализация доступна только как opt-in fallback.
- RTSP-сервер go2rtc выдаёт RTP interleaved по TCP; WebRTC отключён, поэтому bridge-сети и одного TCP mapping достаточно.
- Controller запускается не от root и получает state directory на запись.
- Bearer передаётся controller только как file-backed Compose secret; source
  `environment` не используется из-за различий реализаций Compose.
- Каталог `/config` go2rtc явно монтируется read-only, не создавая анонимный volume; runtime streams восстанавливает controller.
- Docker JSON-логи ограничены по размеру и числу файлов.

## Намеренно НЕ обрабатывает

- Docker Swarm/Kubernetes.
- Hardware video transcoding.
- Автоматическую установку обновлений go2rtc.

## Заметки для агента

> Нельзя задавать Compose network как `internal: true`, потому что обоим контейнерам нужен исходящий доступ: controller к API Ростелекома, go2rtc к медиасерверу камер. Изоляция API достигается отсутствием host port и Basic Auth, а не запретом egress.
