# Архитектура RT Key → go2rtc для SprutHub

## Системный контекст

```text
┌──────────────────────────┐        HTTPS        ┌───────────────────────────┐
│ API «Ростелеком Ключ»    │◄────────────────────│ controller                │
│ новый API + старый API   │                     │ обнаружение и refresh     │
└─────────────┬────────────┘                     └─────────────┬─────────────┘
              │ временный HTTPS-поток                          │ Basic Auth
              │                                               │ PATCH /api/streams
              ▼                                               ▼
┌──────────────────────────┐                     ┌───────────────────────────┐
│ медиасервер камеры       │◄────────────────────│ go2rtc 1.9.14             │
│ host из streamerUrl      │       FFmpeg copy   │ API только Docker-сеть    │
└──────────────────────────┘                     └─────────────┬─────────────┘
                                                              │ RTSP :8554
                                                              │ spruthub/password
                                                              ▼
                                                ┌───────────────────────────┐
                                                │ SprutHub                  │
                                                │ постоянные имена по title │
                                                └───────────────────────────┘
```

На целевом Linux-сервере работают два контейнера. Наружу публикуется только TCP-порт RTSP `8554`. Порт API `1984` доступен контейнеру `controller` по внутреннему имени `go2rtc`, но не публикуется на интерфейсах сервера.

## Компоненты

| Компонент | Ответственность | Публичный интерфейс |
|---|---|---|
| Docker Compose | Запускает два сервиса, сеть, volumes и healthcheck | `docker compose up -d` |
| `controller` | Получает камеры, планирует refresh, обновляет go2rtc | CLI `run`, `sync-once`, `show`, `status`, `healthcheck` |
| Клиент Ростелекома | Новый API, pagination, fallback и нормализация | `fetch_feeds()` |
| Реестр камер | Стабильное соответствие UID → title-based name | `StreamNamingPolicy.reconcile()` |
| Построитель source | Безопасно формирует URL и применяет media profile | `build_go2rtc_source()` |
| Политика аудио | Выбирает copy/transcode глобально или для камеры | `profile_for()` |
| Клиент go2rtc | Создаёт и заменяет runtime-stream через PATCH | `upsert_stream()` |
| Планировщик refresh | Использует минимальный JWT `exp`, margin и retry | `SynchronizeVideoFeeds.refresh_once()` |
| Хранилище состояния | Атомарно сохраняет mapping и last-known-good | `load()`, `save()` |
| RTSP probe | Коротко проверяет каждый lazy upstream через DESCRIBE | `probe()` |
| Установщик | Получает секреты и печатает RTSP-ссылки | `./install.sh`, `./manage.sh show` |

## DDD-границы и правило зависимостей

Проект использует DDD-lite и hexagonal architecture. Это один модульный controller, а не набор микросервисов. Граница проводится по бизнес-возможностям, а не по внешним endpoint.

```text
interfaces / composition root
              │
              ▼
application use cases ─────► application ports
              │                       ▲
              ▼                       │ implements
domain: video gateway       infrastructure adapters
                             ├─ rtkey video catalog
                             ├─ go2rtc media gateway
                             └─ JSON state repository

shared kernel: AccessTokenSource, Clock, typed errors
```

Допустимое направление импортов (слои могут зависеть от shared kernel напрямую):

```text
domain ← application ← infrastructure/interfaces
  shared kernel ← любой слой (только узкие общие контракты)
```

Домен не импортирует `requests`, JSON, Docker, go2rtc или названия полей Ростелекома. Application layer знает только domain types и Protocol-порты. Infrastructure реализует эти порты и выполняет anti-corruption mapping внешних JSON в доменные типы. Composition root — единственное место, где конкретные адаптеры собираются вместе.

### Bounded context: Video Gateway

Реализуется в v1. Владеет понятиями `CameraId`, `CameraFeed`, `StreamName`, `CameraBinding`, `MediaProfile`, синхронизацией источников и сроком их действия. Он не знает, что камера может быть частью домофона или шлагбаума.

### Bounded context: Access Control

Зарезервирован для будущего. Будет владеть `AccessPointId`, `AccessPoint`, командой `OpenAccessPoint` и отдельным `AccessControlProvider` port. Домофоны и шлагбаумы Ростелекома будут адаптированы из `household.../intercom`, `household.../barrier` и команды открытия, но не попадут в `VideoCatalogPort`.

### Bounded context: Intercom Calls

Зарезервирован для будущего. Будет владеть `CallSession`, состояниями звонка, сигнализацией и двусторонним аудио. Для него допускается отдельный async runtime или контейнер только после исследования протокола. Он может ссылаться на `CameraId` через явное сопоставление устройств, но не изменяет агрегат Video Gateway.

### Shared kernel

Shared kernel намеренно минимален и реализован в `shared/ports.py` плюс `errors.py`: время, типизированные ошибки и источник Bearer Token. Нельзя заранее создавать общий `Device` или универсальный `RostelecomGateway`: камеры, точки доступа и звонки имеют разные жизненные циклы и команды.

## Data flow

1. Установщик получает Bearer Token без вывода на экран и сохраняет его в закрытом `.env` с правами `0600`. Compose создаёт из значения secret-файл с владельцем UID/GID controller; в обычное окружение контейнера Bearer не передаётся.
2. Установщик генерирует отдельные случайные пароли для RTSP и внутреннего API go2rtc.
3. Docker Compose запускает `go2rtc` с пустым набором `streams`, RTSP-аутентификацией и API без публикации порта на хост.
4. `controller` ждёт готовности API go2rtc.
5. Если существует last-known-good с ещё действующими streamer-токенами, контроллер восстанавливает эти runtime-streams.
6. Контроллер вызывает новый endpoint `camera_video_data/list`, проходя страницы до конца.
7. При транспортной ошибке, неподдерживаемом статусе или неверной структуре нового API контроллер один раз пробует старый endpoint `api/v1/cameras`.
8. Ответ любого API преобразуется в единый доменный `CameraFeed`.
9. Реестр сохраняет прежнее имя для известного UID. Для новой камеры он транслитерирует и нормализует `title`; при пустом или конфликтующем title добавляет короткую часть UID.
10. Из `streamerUrl` извлекается origin медиасервера; фиксированный `live-vdk4` не используется.
11. Для каждой валидной камеры строится `ffmpeg:` source с копированием видео и выбранным режимом аудио.
12. Контроллер выполняет `PATCH /api/streams?name=<name>&src=<source>`. В go2rtc 1.9.14 PATCH создаёт отсутствующий runtime-stream и меняет существующий без перезапуска процесса.
13. Controller выполняет короткий авторизованный RTSP `DESCRIBE`, который заставляет lazy stream подключиться к upstream.
14. Только после успешного probe URL, срок и media profile становятся last-known-good. При ошибке прежние upstream и profile немедленно возвращаются через PATCH.
15. Следующее обновление назначается за 15 минут до самого раннего корректного `exp`. Если `exp` отсутствует, применяется консервативный интервал четыре часа.
16. SprutHub постоянно использует одну RTSP-ссылку; смена upstream-токена для него прозрачна.
17. Между обновлениями токенов controller раз в минуту сверяет runtime-имена; после отдельного restart go2rtc пропавшие потоки восстанавливаются из ещё действующего LKG без вызова Ростелеком API.

## Ключевые интерфейсы

Ниже показаны сокращённые контракты реализованного ядра.

```python
@dataclass(frozen=True)
class CameraFeed:
    camera_id: CameraId
    title: str
    upstream_url: SecretUrl
    expires_at: int | None

@dataclass
class CameraBinding:
    camera_id: CameraId
    stream_name: StreamName
    title: str
    last_good_upstream: SecretUrl | None
    last_good_profile: MediaProfile | None
    last_good_expires_at: int | None

@dataclass(frozen=True)
class MediaProfile:
    video_mode: Literal["copy"]
    audio_mode: Literal["copy", "aac", "pcma", "pcmu", "none"]

class VideoCatalogPort(Protocol):
    def fetch_feeds(self) -> list[CameraFeed]: ...

class VideoStateRepository(Protocol):
    def load(self) -> GatewayState: ...
    def save(self, state: GatewayState) -> None: ...

class MediaGatewayPort(Protocol):
    def wait_ready(self, timeout: float) -> None: ...
    def upsert_stream(self, name: StreamName, upstream: SecretUrl,
                      profile: MediaProfile) -> None: ...
    def list_streams(self) -> set[str]: ...

class MediaProbePort(Protocol):
    def probe(self, stream_names: set[str]) -> MediaProbeResult: ...

class AccessTokenSource(Protocol):
    def read(self) -> str: ...
```

Новый API:

```text
GET https://keyapis.key.rt.ru/vc/api/v1/camera_video_data/list
    ?paging.limit=100
    &paging.offset=0
```

Старый fallback:

```text
GET https://vc.key.rt.ru/api/v1/cameras?limit=100&offset=0
```

Общий source:

```text
ffmpeg:https://<host-from-streamerUrl>/stream/<uid>/live.mp4
  ?mp4-fragment-length=0.5&mp4-use-speed=0&mp4-afiller=1&token=<urlencoded-token>
  #video=copy#audio=<copy|aac|pcma|pcmu>
```

## Инварианты

- Один `CameraId` связан ровно с одним постоянным `StreamName`.
- Один `stream_name` не может принадлежать разным UID.
- Изменение порядка камер в API не меняет RTSP-ссылки.
- Controller/status не выводят `streamer_token`, Bearer Token и пароли; media-логи go2rtc/FFmpeg считаются чувствительными.
- Last-known-good не заменяется данными, которые не прошли нормализацию, PATCH и RTSP/upstream probe.
- API go2rtc не публикуется на host-порт.
- RTSP всегда требует username и password для подключений из LAN.
- Ошибка одной камеры не отменяет успешное обновление остальных камер.

## Технологические решения

| Решение | Выбор | Обоснование |
|---|---|---|
| Оркестрация | Docker Compose, два сервиса | Простой перенос и независимые жизненные циклы |
| Контроллер | `python:3.12.14-alpine3.24`, синхронный цикл | Воспроизводимый multi-arch base; runtime без сторонних Python-пакетов |
| HTTP | Python `urllib` с TLS verification, timeout и запретом redirects | Нет runtime-зависимостей; Bearer не уйдёт на другой host через redirect |
| go2rtc | `alexxit/go2rtc:1.9.14` | Фиксированная multi-arch версия с FFmpeg внутри |
| Видео | `video=copy` | Нет перекодирования и лишней нагрузки CPU |
| Аудио | Отдельная политика, `audio=copy` по умолчанию | Позволяет глобальные и будущие per-camera профили без изменения URL/API-модулей |
| Runtime update | `PATCH /api/streams` | Не требует restart и умеет создать отсутствующий stream |
| Состояние | Версионированный JSON в volume | Небольшой объём, прозрачно и достаточно надёжно |
| API security | Внутренняя Docker-сеть + Basic Auth | Контроллер доступен, LAN-доступ отсутствует |
| Проверка здесь | Unit/contract/static tests | Docker отсутствует по условию владельца проекта |
| Архитектурный стиль | DDD-lite + ports/adapters | Изолирует домен от изменений Ростелекома и go2rtc без микросервисной сложности |

## Режимы отказа

| Сбой | Влияние | Митигация |
|---|---|---|
| Новый API недоступен | Нельзя получить свежие данные | Немедленный fallback на старый API |
| Оба API недоступны | Токены не обновляются | Сохранить runtime и last-known-good; retry с backoff |
| Bearer Token истёк | Новые streamer-токены недоступны | Явный unhealthy и команда замены токена; секрет не логировать |
| JWT не содержит `exp` | Нельзя вычислить точный refresh | Обновлять раз в четыре часа |
| `streamerUrl` отсутствует/опасен | Нельзя доверять записи камеры | Пропустить дефектную запись, сохранить валидные камеры; если валидных нет — попробовать fallback и оставить прежний LKG |
| PATCH/probe одной камеры не прошёл | Новая конфигурация этой камеры отклоняется | Вернуть её прежние upstream и media profile, не менять LKG, повторить отдельно |
| go2rtc перезапущен | Runtime-streams исчезли | Controller повторно применяет LKG и свежие sources |
| Повреждён state JSON | Потеря стабильного mapping | Не перезаписывать файл; использовать резервную копию и аварийный статус |
| Аудиокодек не принят SprutHub | Видео есть, звука нет | `AUDIO_MODE=aac`, затем `pcma` или `pcmu`; видео остаётся copy |
| Камера исчезла из API | Старый endpoint остаётся, но upstream истечёт | Пометить отсутствующей; не переиспользовать её имя автоматически |
| Порт 8554 занят | RTSP не запускается | Явная ошибка Compose; поддержать настраиваемый host-порт |

## Проверка без Docker

- Unit-тесты всех чистых преобразований и расчёта времени.
- HTTP contract-тесты с поддельным transport для обоих форматов API, pagination, fallback и ошибок.
- Тесты клиента go2rtc с локальным mock HTTP server, включая Basic Auth и URL encoding.
- Локальный mock RTSP server для авторизованного `DESCRIBE`, без получения реального видео.
- Тесты атомарной записи state во временный каталог.
- Проверка YAML и результата подстановки переменных Compose парсером, если он доступен без запуска daemon.
- Проверка shell-скриптов через `bash -n` и ShellCheck, если утилита установлена.
- Запрет в тестах на реальные обращения к Ростелекому и запуск Docker.

## Вне области видимости v1

- Автоматическое получение нового Bearer Token через телефон, пароль или обход captcha.
- Архив Ростелекома и двустороннее аудио.
- ONVIF, WebRTC и публикация Web UI go2rtc в LAN.
- Транскодирование видео и аппаратное ускорение.
- Автоматическое управление firewall удалённого сервера.
- Поддержка Kubernetes, Windows containers и нескольких аккаунтов Ростелекома.
- Гарантия совместимости с недокументированными будущими изменениями API.
- Реализация открытия дверей/шлагбаумов и обработки звонков; для них определены отдельные bounded contexts, но нет фиктивного кода.
