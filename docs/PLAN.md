# План модернизации RT Key → go2rtc

## Статус

Основная реализация завершена. Старый systemd/cron-вариант заменён Docker
Compose-развёртыванием из двух контейнеров. После первой серверной проверки
добавлены on-demand snapshot, video-only H.264 copy и ленивый
healthcheck. На машине разработки Docker намеренно не запускался; выполнены
unit/contract/architecture-тесты и статические проверки. Осталась повторная
приёмка на целевом Linux-сервере.

## Карта атомарных модулей

| Фаза | Самодостаточные спецификации |
|---|---|
| 1 | [Application ports](../modules/application_ports.md), [Shared kernel](../modules/shared_kernel.md), [Будущие контексты](../modules/future_contexts.md) |
| 2 | [Docker runtime](../modules/docker_runtime.md) |
| 3 | [Клиент Ростелекома](../modules/rostekey_api.md) |
| 4 | [Реестр камер](../modules/camera_registry.md), [State store](../modules/state_store.md) |
| 5 | [Контроллер refresh](../modules/refresh_controller.md), [Клиент go2rtc](../modules/go2rtc_client.md) |
| 6 | [Media policy](../modules/audio_policy.md), [Построитель source](../modules/stream_source.md), [Диагностика](../modules/healthcheck.md), [Snapshot endpoint](../modules/snapshot_endpoint.md) |
| 7 | [Быстрый старт](../modules/quick_start.md) |
| 8 | [Управление доступом](../modules/access_control.md) |

## Фаза 1 — Архитектурный baseline

**Цель**: отделить предметную модель от Ростелеком API, go2rtc, Docker и файловой системы.
**Результат**: DDD-lite/ports-and-adapters, один bounded context Video Gateway и отдельные границы будущих Access Control/Intercom Calls.
**Статус**: [x] Завершена

### Выполнено

- [x] Зафиксировано направление `domain ← application ← infrastructure/interfaces`.
- [x] Определены узкие ports без JSON, HTTP response и go2rtc query string.
- [x] Источник Bearer Token и часы вынесены в минимальный [shared kernel](../modules/shared_kernel.md).
- [x] Добавлен автоматический тест направленности импортов.
- [x] Приняты [ADR-0001](adr/0001-stack.md) и [ADR-0006](adr/0006-domain-boundaries.md).

### Rollback

Архитектурные документы не меняют runtime и могут быть откатаны обычным Git revert.

## Фаза 2 — Docker runtime и безопасность

**Цель**: воспроизводимо запускать media gateway и controller с разными жизненными циклами.
**Результат**: два контейнера, закреплённый go2rtc 1.9.14, отдельный volume
состояния и два узких опубликованных интерфейса: RTSP и JPEG snapshot.
**Статус**: [x] Реализована, [ ] проверена на целевом сервере

### Выполнено

- [x] API go2rtc не опубликован на host и ограничен `/api/streams` и
  `/api/frame.jpeg` для внутреннего controller.
- [x] Включены Basic Auth и `local_auth` для внутреннего API.
- [x] RTSP требует отдельный логин/пароль.
- [x] Controller работает не от root, filesystem read-only; capabilities удалены.
- [x] Добавлены ограничения процессов, tmpfs, healthcheck и restart policy.
- [x] Snapshot публикуется отдельным Basic-auth endpoint без доступа к Web UI/API.

### Проверка

- [x] Статический тест запрещает mapping `1984:1984`.
- [ ] `docker compose config --quiet` на целевом сервере.
- [ ] Перезапуск каждого контейнера и проверка сохранения RTSP URL.

### Rollback

`./manage.sh down` останавливает Compose без удаления закрытых `.env`,
`secrets/rtkey_access_token` и volume.

## Фаза 3 — Anti-corruption layer Ростелекома

**Цель**: переживать сосуществование и последующие изменения API камер.
**Результат**: новый endpoint имеет приоритет, legacy дополняет отсутствующие UID
и служит fallback; оба преобразуются в один `CameraFeed`.
**Статус**: [x] Завершена

### Выполнено

- [x] Независимые `NewCameraApiStrategy` и `LegacyCameraApiStrategy`.
- [x] Pagination, защита от повторяющихся страниц и ограничение числа страниц.
- [x] Строгая валидация ответа перед заменой last-known-good.
- [x] Host берётся из `streamerUrl`, проверяется allowlist suffix и не привязан к `live-vdk4`.
- [x] Redirects запрещены, чтобы Bearer не ушёл на другой host.
- [x] Успешные ответы обоих API объединяются по UID без дублирования камер.

### Тесты

- [x] Оба формата JSON, fallback, auth errors и неверная схема.
- [x] Динамический media host, URL encoding токена и запрет чужого домена.

### Rollback

Новая стратегия отключается в composition root без изменения domain/use case.

## Фаза 4 — Стабильные имена и состояние

**Цель**: навсегда отвязать публичный RTSP URL от порядка ответа API.
**Результат**: title-based slug закрепляется за UID; прежние имена резервируются для исчезнувших камер.
**Статус**: [x] Завершена

### Выполнено

- [x] Детерминированная транслитерация, UID suffix для пустых/одинаковых title.
- [x] Версионированный JSON, temp + fsync + atomic replace и валидный backup.
- [x] Строгая проверка типов, UID keys и уникальности stream names при загрузке.
- [x] Sanitize внешнего title/UID и безопасный status без upstream secrets.

### Rollback

Сохранить Docker volume до отката: он содержит mapping UID → постоянное имя.

## Фаза 5 — Обновление без остановки RTSP

**Цель**: менять временные upstream tokens без restart go2rtc.
**Результат**: `PATCH /api/streams`, расписание по JWT `exp`, независимая обработка камер и last-known-good.
**Статус**: [x] Реализована, [ ] подтверждена с реальными камерами

### Выполнено

- [x] Refresh за 15 минут до самого раннего `exp`.
- [x] Четырёхчасовой fallback для токена без корректного `exp`.
- [x] Ограниченный retry/backoff и отдельная классификация Bearer auth error.
- [x] LKG сохраняется только после PATCH, проверки имени через GET и успешного RTSP/upstream probe.
- [x] При неудачном probe прежние upstream и media profile возвращаются отдельным PATCH.
- [x] После restart восстанавливаются только активные и ещё действующие bindings.
- [x] После отдельного restart go2rtc controller обнаруживает пропавшие runtime-streams не позднее чем через минуту и восстанавливает действующий LKG без запроса к Ростелекому.
- [x] Если API повторно вернул тот же token/profile, PATCH и media probe
  пропускаются, поэтому активный consumer не обрывается и FFmpeg не запускается.

### Проверка

- [x] Mock go2rtc проверяет PATCH, Basic Auth, source и частичный отказ.
- [ ] На сервере дождаться реального refresh и подтвердить, что RTSP URL не изменился.

### Rollback

Остановить controller; работающий go2rtc сохранит текущие runtime-streams до своего restart или истечения upstream token.

## Фаза 6 — Совместимый ленивый media и snapshot

**Цель**: устранить зелёный экран, предоставить snapshot и не расходовать CPU без потребителей.
**Результат**: один video-only H.264 copy source и защищённый JPEG URL каждой камеры.
**Статус**: [x] Реализована, [ ] проверена в SprutHub

### Выполнено

- [x] Media policy независимо выбирает video/audio профиль глобально или по UID
  (→ [Модуль media policy](../modules/audio_policy.md)).
- [x] Удалена небезопасная подмена timestamps wallclock; copy использует
  demuxer time base без video decode/encode
  (→ [Модуль source](../modules/stream_source.md)).
- [x] Неподдерживаемые уменьшенные варианты убраны из обычной установки и вывода.
- [x] Автоматический healthcheck использует RTSP `OPTIONS` и не будит upstream;
  глубокий `DESCRIBE` доступен через `check-streams`
  (→ [Модуль диагностики](../modules/healthcheck.md)).
- [x] `show` печатает RTSP и snapshot URL каждой камеры
  (→ [Модуль snapshot](../modules/snapshot_endpoint.md)).
- [x] Одновременные initial probes ограничены одним worker, snapshot — двумя.
- [x] После полевой диагностики PCMU исключён из стабильного профиля, HTTP read
  timeout снижен с 15 до 5 секунд, RTSP по умолчанию объявляет только video.

### Проверка

- [x] Unit-тесты video/audio modes, миграции PCMU → none, snapshot Basic Auth и локальный mock RTSP server.
- [x] На реальных исходных RTSP подтверждены H.264, AAC-LC 48 kHz mono,
  keyframe примерно раз в секунду и нестабильные DTS.
- [ ] VLC: стабильность video-only H.264.
- [ ] SprutHub: стабильность video-only H.264 после повторного добавления камеры.
- [ ] SprutHub: получение snapshot по напечатанному HTTP URL.

### Rollback

Вернуть предыдущий Git revision и повторно выполнить installer. Публичные
базовые URL и UID mapping сохраняются.

## Фаза 7 — Передача и расширение

**Цель**: обеспечить повторяемый быстрый старт и не закрыть путь к новым функциям.
**Результат**: installer/manager/uninstaller, CI без секретов и контракт будущих bounded contexts.
**Статус**: [x] Реализована, [ ] завершена приёмка владельцем

### Выполнено

- [x] Старые systemd/cron-файлы удалены из основного deployment path.
- [x] CI компилирует Python, запускает офлайн-тесты, проверяет shell и Compose без старта контейнеров.
- [x] Access Control моделируется будущей одноразовой командой с авторизацией/audit, а не частью камеры.
- [x] Intercom Calls получает отдельный жизненный цикл и media/signaling ports.

### Приёмка

- [ ] Выполнить [чек-лист первого запуска](TROUBLESHOOTING.md#чек-лист-первого-запуска).
- [ ] Ограничить firewall доступом к 8554 и 8080 только с IP SprutHub, если LAN недоверенная.
- [ ] Зафиксировать Git-тег после успешной приёмки.

### Rollback

Использовать предыдущий Git-тег. Не удалять volume, закрытый `.env` и каталог
`secrets/` до подтверждения стабильной работы выбранной версии.

## Фаза 8 — Кнопки открытия SprutHub через MQTT

**Цель**: добавить домофоны и шлагбаумы как opt-in устройства SprutHub без раскрытия Bearer Token.
**Результат**: существующий controller подключается к встроенному MQTT broker, публикует retained Switch и выполняет проверенную одноразовую команду открытия.
**Статус**: [x] Реализована, [ ] проверена на целевом сервере и SprutHub

### Выполнено

- [x] Отдельные domain types, application ports и JSON state Access Control.
- [x] Независимые endpoint `intercom`/`barrier`, partial refresh и generic open.
- [x] Paho MQTT 2.1.0, reconnect, retained discovery и актуальный SprutHub template.
- [x] Запрет retained open, allowlist каталога, bounded queue, duplicate detection и cooldown.
- [x] Режим `off` не создаёт worker, MQTT client и provider calls.
- [x] Installer/manager печатают настройки и соответствие provider title → MQTT key.

### Проверка

- [x] Unit/contract-тесты domain, API mapping, state, MQTT topics и open policy.
- [ ] Импортировать `spruthub/rtkey_access_v2.json` и обнаружить все retained устройства.
- [ ] Проверить по одному открытию домофона и шлагбаума с безопасного места.
- [ ] Отключить broker, убедиться в сохранении видео и автоматическом reconnect.

### Rollback

Повторно выполнить `./install.sh --access-control off`. Видео, RTSP и snapshot
продолжат работать; access worker и MQTT connection не создаются.
