# Модуль: Клиент go2rtc

**Ответственность**: безопасно управляет runtime-streams через внутренний HTTP API go2rtc.
**Расположение**: `src/rtkey_gateway/infrastructure/go2rtc_gateway.py`

## Публичный интерфейс

| Символ | Тип | Описание |
|---|---|---|
| `Go2RtcMediaGateway` | class | Клиент API с Basic Auth и timeout |
| `wait_ready()` | метод | Ожидает готовности API в ограниченный срок |
| `upsert_stream()` | метод | Кодирует `name`/`src` и вызывает PATCH `/api/streams` |
| `list_streams()` | метод | Возвращает множество runtime stream names |
| `fetch_jpeg()` | метод | Получает ограниченный JPEG через внутренний `/api/frame.jpeg` |

## Зависимости

| Модуль | Что использует |
|---|---|
| `UrllibTransport` | HTTP, TLS verification, timeout и Basic Auth header |
| `application.ports` | Реализует `MediaGatewayPort` |
| `go2rtc_source` | Преобразует domain types в source конкретного media gateway |

## Инварианты

- Base URL задаётся конфигурацией и по умолчанию равен `http://go2rtc:1984`.
- Каждый запрос имеет connect/read timeout.
- PATCH считается успешным только при 2xx и последующей видимости имени в списке.
- API password не логируется.
- Клиент не вызывает `/api/config`, `/api/restart` и `/api/exit`.
- JPEG проверяется по размеру и сигнатуре до возврата inbound endpoint.

## Намеренно НЕ обрабатывает

- Решение, когда нужен refresh.
- Сохранение last-known-good.
- Публикацию API в LAN.

## Заметки для агента

> В go2rtc 1.9.14 PATCH создаёт отсутствующий runtime-stream и заменяет source существующего. Он не переписывает основной config, поэтому read-only `go2rtc.yaml` с `streams: {}` совместим с этой схемой; после restart controller обязан применить состояние снова.
