# План модернизации RT Key → go2rtc

## Статус

Основная реализация завершена. Старый systemd/cron-вариант заменён Docker Compose-развёртыванием из двух контейнеров. На машине разработки Docker намеренно не запускался; выполнены unit/contract/architecture-тесты и статические проверки. Осталась обязательная ручная приёмка на целевом Linux-сервере с действующим Bearer Token.

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
**Результат**: два контейнера, закреплённый go2rtc 1.9.14, отдельный volume состояния и единственный опубликованный RTSP-порт.
**Статус**: [x] Реализована, [ ] проверена на целевом сервере

### Выполнено

- [x] API go2rtc не опубликован на host и ограничен `/api/streams`.
- [x] Включены Basic Auth и `local_auth` для внутреннего API.
- [x] RTSP требует отдельный логин/пароль.
- [x] Controller работает не от root, filesystem read-only; capabilities удалены.
- [x] Добавлены ограничения процессов, tmpfs, healthcheck и restart policy.

### Проверка

- [x] Статический тест запрещает mapping `1984:1984`.
- [ ] `docker compose config --quiet` на целевом сервере.
- [ ] Перезапуск каждого контейнера и проверка сохранения RTSP URL.

### Rollback

`./manage.sh down` останавливает Compose без удаления закрытых `.env`,
`secrets/rtkey_access_token` и volume.

## Фаза 3 — Anti-corruption layer Ростелекома

**Цель**: переживать сосуществование и последующие изменения API камер.
**Результат**: новый endpoint используется первым, legacy — fallback; оба преобразуются в один `CameraFeed`.
**Статус**: [x] Завершена

### Выполнено

- [x] Независимые `NewCameraApiStrategy` и `LegacyCameraApiStrategy`.
- [x] Pagination, защита от повторяющихся страниц и ограничение числа страниц.
- [x] Строгая валидация ответа перед заменой last-known-good.
- [x] Host берётся из `streamerUrl`, проверяется allowlist suffix и не привязан к `live-vdk4`.
- [x] Redirects запрещены, чтобы Bearer не ушёл на другой host.

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

### Проверка

- [x] Mock go2rtc проверяет PATCH, Basic Auth, source и частичный отказ.
- [ ] На сервере дождаться реального refresh и подтвердить, что RTSP URL не изменился.

### Rollback

Остановить controller; работающий go2rtc сохранит текущие runtime-streams до своего restart или истечения upstream token.

## Фаза 6 — Аудио и диагностика

**Цель**: пропустить исходный звук и оставить независимый путь транскодирования.
**Результат**: `copy`, `aac`, `pcma`, `pcmu`, `none`, включая overrides по UID; video всегда copy.
**Статус**: [x] Реализована, [ ] проверена в SprutHub

### Выполнено

- [x] Media policy не зависит от API Ростелекома и публичных RTSP URL.
- [x] Healthcheck сверяет state, go2rtc API, JWT expiry и выполняет короткий авторизованный RTSP `DESCRIBE` каждого upstream.
- [x] `show` печатает все камеры, UID, логин, пароль и готовые ссылки.

### Проверка

- [x] Unit-тесты всех audio modes и локальный mock RTSP server.
- [ ] VLC: видео и наличие аудиодорожки.
- [ ] SprutHub: `copy`, при необходимости `aac` → `pcma` → `pcmu`.

### Rollback

Вернуть `AUDIO_MODE=copy` или `none` и выполнить `./manage.sh refresh`; go2rtc не останавливается.

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
- [ ] Ограничить firewall доступом к 8554 только с IP SprutHub, если LAN недоверенная.
- [ ] Зафиксировать Git-тег после успешной приёмки.

### Rollback

Использовать предыдущий Git-тег. Не удалять volume, закрытый `.env` и каталог
`secrets/` до подтверждения стабильной работы выбранной версии.
