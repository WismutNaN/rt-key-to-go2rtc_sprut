# Модуль: Диагностика

**Ответственность**: определяет готовность controller/go2rtc и даёт безопасный чек-лист проверки на целевом сервере.
**Расположение**: `src/rtkey_gateway/application/health.py`, `src/rtkey_gateway/infrastructure/rtsp_probe.py`, `src/rtkey_gateway/interfaces/cli.py`, `docs/TROUBLESHOOTING.md`

## Публичный интерфейс

| Символ | Тип | Описание |
|---|---|---|
| `HealthReport` | dataclass | `healthy`, `degraded` и безопасные причины |
| `evaluate_state()` | функция | Проверяет свежесть fetch, token exp, API и RTSP-пробы |
| `Go2RtcRtspProbe` | adapter | Параллельно выполняет короткий DESCRIBE с credentials |
| `healthcheck` | CLI | Возвращает exit code для Compose |

## Зависимости

| Модуль | Что использует |
|---|---|
| `application.ports` | State repository и media gateway ports |
| `domain.video` | Ожидаемые bindings и сроки |
| Python sockets | TCP/RTSP handshake без запуска постоянного consumer |

## Инварианты

- Healthcheck ограничен коротким timeout и не скачивает видео постоянно.
- `healthy` требует доступный go2rtc и как минимум один ожидаемый stream после успешного обнаружения.
- Истёкший Bearer даёт понятный `degraded/unhealthy`, а не бесконечный restart loop.
- Status/health/controller log не содержат credentials или upstream source; go2rtc/FFmpeg logs считаются чувствительными.
- Проверка RTSP использует внутренний адрес go2rtc и не определяет доступность LAN firewall.

## Намеренно НЕ обрабатывает

- Оценку качества видео и синхронизации звука.
- Доступность SprutHub как клиента.
- Автоматическое изменение аудиокодека.

## Заметки для агента

> Ручная проверка на целевом сервере обязательна: открыть каждый RTSP URL в VLC, затем добавить в SprutHub. Для звука проверять режимы в порядке `copy`, `aac`, `pcma`, `pcmu`; после каждого изменения выполнить `./manage.sh refresh` и переподключить клиент. Если video copy работает, аудио-транскодирование не меняет видеопараметры.
