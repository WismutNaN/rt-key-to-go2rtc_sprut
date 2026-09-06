# Модуль: Диагностика

**Ответственность**: определяет готовность controller/go2rtc и даёт безопасный чек-лист проверки на целевом сервере.
**Расположение**: `src/rtkey_gateway/application/health.py`, `src/rtkey_gateway/infrastructure/rtsp_probe.py`, `src/rtkey_gateway/interfaces/cli.py`, `docs/TROUBLESHOOTING.md`

## Публичный интерфейс

| Символ | Тип | Описание |
|---|---|---|
| `HealthReport` | dataclass | `healthy`, `degraded` и безопасные причины |
| `evaluate_state()` | функция | Проверяет свежесть fetch, token exp, API и RTSP-пробы |
| `Go2RtcRtspProbe` | adapter | Выполняет OPTIONS или ограниченный DESCRIBE с credentials |
| `healthcheck` | CLI | Проверяет server/state, не запуская media producer |
| `deep-healthcheck` | CLI | Разово запускает и проверяет каждый upstream |

## Зависимости

| Модуль | Что использует |
|---|---|
| `application.ports` | State repository и media gateway ports |
| `domain.video` | Ожидаемые bindings и сроки |
| Python sockets | TCP/RTSP handshake без запуска постоянного consumer |

## Инварианты

- Автоматический healthcheck делает только RTSP `OPTIONS` и не будит upstream.
- Deep healthcheck выполняется только явно; probes ограничены одним worker по умолчанию.
- `healthy` требует доступный go2rtc и как минимум один ожидаемый stream после успешного обнаружения.
- Истёкший Bearer даёт понятный `degraded/unhealthy`, а не бесконечный restart loop.
- Status/health/controller log не содержат credentials или upstream source; go2rtc/FFmpeg logs считаются чувствительными.
- Проверка RTSP использует внутренний адрес go2rtc и не определяет доступность LAN firewall.

## Намеренно НЕ обрабатывает

- Оценку качества видео и синхронизации звука.
- Доступность SprutHub как клиента.
- Автоматическое изменение аудиокодека.

## Заметки для агента

> Ручная проверка на целевом сервере обязательна: выполнить
> `./manage.sh check-streams`, открыть каждый RTSP URL в VLC, затем добавить в
> SprutHub. Команда временно запускает обработку всех камер, но делает это
> последовательно; обычный healthcheck оставляет media выключенным.
