# Архитектура RT Key → go2rtc для SprutHub

## Системный контекст

```text
┌──────────────────────────┐        HTTPS        ┌───────────────────────────┐
│ API «Ростелеком Ключ»    │◄────────────────────│ controller                │
│ video + access API       │                     │ video/access workers      │
└─────────────┬────────────┘                     └─────────────┬─────────────┘
              │ временный HTTPS-поток                          │ Basic Auth
              │                                               │ PATCH /api/streams
              ▼                                               ▼
┌──────────────────────────┐                     ┌───────────────────────────┐
│ медиасервер камеры       │◄────────────────────│ go2rtc 1.9.14             │
│ host из streamerUrl      │    ленивый FFmpeg   │ API только Docker-сеть    │
└──────────────────────────┘                     └─────────────┬─────────────┘
                                                              │ RTSP :8554
                                                              │ spruthub/password
                                                              ▼
                                                ┌───────────────────────────┐
                                                │ SprutHub                  │
                                                │ RTSP, snapshot, MQTT      │
                                                └───────────────────────────┘
```

На целевом Linux-сервере работают два контейнера. Наружу публикуются RTSP
`8554/tcp` и узкий HTTP snapshot endpoint `8080/tcp`, оба с credentials
SprutHub. Порт API `1984` доступен контейнеру `controller` по внутреннему имени
`go2rtc`, но не публикуется на интерфейсах сервера.
При `ACCESS_CONTROL=mqtt` controller дополнительно устанавливает исходящее
соединение с broker SprutHub `44444/tcp`; новый входящий порт на Docker-сервере
не появляется.

## Компоненты

| Компонент | Ответственность | Публичный интерфейс |
|---|---|---|
| Docker Compose | Запускает два сервиса, сеть, volumes и healthcheck | `docker compose up -d` |
| `controller` | Получает камеры, планирует refresh, обновляет go2rtc и отдаёт JPEG | CLI `run`, `sync-once`, `show`, `status`, `healthcheck`, HTTP snapshot |
| Клиент Ростелекома | Новый API, legacy completion/fallback, pagination и нормализация | `fetch_feeds()` |
| Реестр камер | Стабильное соответствие UID → title-based name | `StreamNamingPolicy.reconcile()` |
| Построитель source | Безопасно формирует URL и применяет media profile | `build_go2rtc_source()` |
| Media policy | Выбирает video/audio профиль и разрешения глобально или по UID | `profile_for()`, `variants_for()` |
| Клиент go2rtc | Создаёт runtime-stream, меняет source и получает JPEG | `upsert_stream()`, `fetch_jpeg()` |
| Планировщик refresh | Использует минимальный JWT `exp`, margin и retry | `SynchronizeVideoFeeds.refresh_once()` |
| Хранилище состояния | Атомарно сохраняет mapping и last-known-good | `load()`, `save()` |
| RTSP probe | Проверяет сервер через OPTIONS или явно будит upstream через DESCRIBE | `probe()` |
| Snapshot interface | Отдаёт только JPEG проверенных камер с Basic Auth | `GET /snapshot/<name>.jpg` |
| Установщик | Получает секреты и печатает RTSP/snapshot-ссылки | `./install.sh`, `./manage.sh show` |
| Access control service | Независимо обновляет intercom/barrier и сериализует open | `refresh_once()`, `handle_command()` |
| Access API adapter | Нормализует две категории устройств и выполняет open | `fetch_access_points()`, `open_access_point()` |
| MQTT adapter | Retained discovery, reconnect и momentary Switch | `rtkey/access/+/state`, `rtkey/access/+/set` |

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

Реализован как opt-in worker внутри controller. Владеет `AccessPointId`,
`AccessPoint`, `AccessBinding`, одноразовой командой открытия и отдельными
`AccessControlProviderPort`/`AccessEventPort`. Домофоны и шлагбаумы адаптируются
из `household.../intercom`, `household.../barrier` и `POST .../{id}/open`, не
попадая в `VideoCatalogPort`. MQTT и JSON остаются infrastructure adapters.

### Bounded context: Intercom Calls

Зарезервирован для будущего. Будет владеть `CallSession`, состояниями звонка, сигнализацией и двусторонним аудио. Для него допускается отдельный async runtime или контейнер только после исследования протокола. Он может ссылаться на `CameraId` через явное сопоставление устройств, но не изменяет агрегат Video Gateway.

### Shared kernel

Shared kernel намеренно минимален и реализован в `shared/ports.py` плюс `errors.py`: время, типизированные ошибки и источник Bearer Token. Нельзя заранее создавать общий `Device` или универсальный `RostelecomGateway`: камеры, точки доступа и звонки имеют разные жизненные циклы и команды.

## Data flow

1. Установщик получает Bearer Token без вывода на экран и атомарно сохраняет
   его в `secrets/rtkey_access_token`. Каталог имеет права `0700`, а файл
   монтируется Compose только в controller как `/run/secrets/rtkey_access_token`.
   В `.env`, обычное окружение контейнера и Docker build context Bearer не
   передаётся. Файл имеет mode `0444`, потому что локальный Compose использует
   bind mount и не меняет владельца под UID `10001`; закрытый родительский
   каталог не позволяет другим host-пользователям прочитать его.
2. Установщик генерирует отдельные случайные пароли для RTSP и внутреннего API go2rtc. Если выбран MQTT, он также сохраняет адрес и credentials broker SprutHub в закрытом `.env`; Bearer Token в SprutHub не передаётся.
3. Docker Compose запускает `go2rtc` с пустым набором `streams`, RTSP-аутентификацией и API без публикации порта на хост.
4. `controller` ждёт готовности API go2rtc.
5. Если существует last-known-good с ещё действующими streamer-токенами, контроллер восстанавливает эти runtime-streams.
6. Контроллер вызывает новый endpoint `camera_video_data/list`, проходя страницы до конца.
7. Затем он вызывает legacy endpoint `api/v1/cameras`: успешный legacy-ответ
   дополняет отсутствующие UID, а при ошибке нового API полностью становится fallback.
8. Ответы преобразуются в единый доменный `CameraFeed`; при одинаковом UID
   приоритет сохраняется за новым API.
9. Реестр сохраняет прежнее имя для известного UID. Для новой камеры он транслитерирует и нормализует `title`; при пустом или конфликтующем title добавляет короткую часть UID.
10. Из `streamerUrl` извлекается origin медиасервера; фиксированный `live-vdk4` не используется.
11. Для каждой валидной камеры строятся три ленивых `ffmpeg:` source: исходный
    размер, 1280x720 и 640x360. По умолчанию они нормализуют H.264 в CFR 30 fps
    и AAC в PCMA; набор размеров настраивается одним списком.
12. Контроллер выполняет отдельный `PATCH /api/streams?name=<name>&src=<source>`
    для каждого варианта. Масштабированные имена получают стабильный суффикс
    `_WIDTHxHEIGHT`. PATCH только регистрирует source и не запускает FFmpeg.
13. Если source и media profile не изменились и все runtime-streams существуют,
    PATCH и probe пропускаются. Пропавший масштабированный variant восстанавливается
    отдельно. Для проверки upstream controller делает `DESCRIBE` только базового
    варианта; initial/changed камеры проверяются последовательно.
14. Только после успешного probe URL, срок и media profile становятся last-known-good. При ошибке прежние upstream и profile немедленно возвращаются через PATCH.
15. Следующее обновление назначается за 15 минут до самого раннего корректного `exp`. Если `exp` отсутствует, применяется консервативный интервал четыре часа.
16. SprutHub постоянно использует одну RTSP-ссылку; смена upstream-токена для него прозрачна.
17. При запросе snapshot controller проверяет binding и через внутренний
    `/api/frame.jpeg` получает один JPEG. Этот запрос является временным consumer.
18. Автоматический healthcheck делает только RTSP `OPTIONS` и не запускает
    media. Полный `DESCRIBE` всех камер выполняется только явной командой
    `./manage.sh check-streams`.
19. Между обновлениями токенов controller раз в минуту сверяет runtime-имена; после отдельного restart go2rtc пропавшие потоки восстанавливаются из ещё действующего LKG без вызова Ростелеком API.
20. При включённом MQTT access worker независимо получает списки `intercom` и
    `barrier`, сохраняя стабильный MQTT key по type/provider ID. Частичный ответ
    обновляет только успешно полученную категорию.
21. MQTT adapter публикует retained `OFF` и metadata каждого устройства. Только
    свежая команда `ON` для известного present key помещается в ограниченную очередь.
22. Application service применяет cooldown, выполняет POST открытия и публикует
    короткий non-retained `ON`, затем retained `OFF`. Retained-команды и `OFF`
    никогда не вызывают provider.

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
    video_mode: Literal["h264", "copy"]
    video_fps: int
    video_width: int | None
    video_height: int | None
    audio_mode: Literal["copy", "aac", "pcma", "pcmu", "none"]

class MediaResolution:
    width: int | None
    height: int | None

class MediaPolicy:
    def profile_for(self, camera_id: str) -> MediaProfile: ...
    def variants_for(self, camera_id: str) -> tuple[MediaVariant, ...]: ...

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

class SnapshotGatewayPort(Protocol):
    def fetch_jpeg(self, name: StreamName) -> bytes: ...

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
  #input=rtkey_http#video=<rtkey_h264_stable|copy>
  #width=<optional-width>#height=<optional-height>
  #audio=<copy|aac|pcma|pcmu>
```

## Инварианты

- Один `CameraId` связан ровно с одним постоянным `StreamName`.
- Один `stream_name` не может принадлежать разным UID.
- Изменение порядка камер в API не меняет RTSP-ссылки.
- Controller/status не выводят `streamer_token`, Bearer Token и пароли; media-логи go2rtc/FFmpeg считаются чувствительными.
- Last-known-good не заменяется данными, которые не прошли нормализацию, PATCH и RTSP/upstream probe.
- Неизменившийся source не заменяется повторным PATCH и не запускает media probe.
- Набор разрешений начинается с `source`, содержит не более четырёх уникальных
  вариантов и использует только чётные размеры H.264.
- API go2rtc не публикуется на host-порт.
- RTSP и snapshot всегда требуют username и password для подключений из LAN.
- Автоматический healthcheck не является media consumer.
- Ошибка одной камеры не отменяет успешное обновление остальных камер.

## Технологические решения

| Решение | Выбор | Обоснование |
|---|---|---|
| Оркестрация | Docker Compose, два сервиса | Простой перенос и независимые жизненные циклы |
| Контроллер | `python:3.12.14-alpine3.24`, два независимых worker | Воспроизводимый multi-arch base; сбой access не останавливает video |
| MQTT | Eclipse Paho 2.1.0, MQTT 3.1.1 | Стабильный reconnect и совместимость со встроенным broker SprutHub |
| HTTP | Python `urllib` с TLS verification, timeout и запретом redirects | Нет runtime-зависимостей; Bearer не уйдёт на другой host через redirect |
| go2rtc | `alexxit/go2rtc:1.9.14` | Фиксированная multi-arch версия с FFmpeg внутри |
| Видео | Ленивый H.264 CFR 30 fps; source/720p/360p; per-UID `copy` | Устраняет нестабильные DTS и позволяет выбирать нагрузку без фонового CPU |
| Аудио | Отдельная политика, `audio=pcma` по умолчанию | Повышает совместимость SprutHub; AAC/copy/PCMU остаются настраиваемыми |
| Snapshot | Basic-auth proxy к внутреннему `/api/frame.jpeg` | SprutHub получает JPEG, а общий API go2rtc остаётся закрыт |
| Runtime update | `PATCH /api/streams` | Не требует restart и умеет создать отсутствующий stream |
| Состояние | Версионированный JSON в volume | Небольшой объём, прозрачно и достаточно надёжно |
| API security | Внутренняя Docker-сеть + Basic Auth | Контроллер доступен, LAN-доступ отсутствует |
| Проверка здесь | Unit/contract/static tests | Docker отсутствует по условию владельца проекта |
| Архитектурный стиль | DDD-lite + ports/adapters | Изолирует домен от изменений Ростелекома и go2rtc без микросервисной сложности |

## Режимы отказа

| Сбой | Влияние | Митигация |
|---|---|---|
| Новый API недоступен | Нельзя получить свежие данные | Legacy API становится fallback |
| Новый API вернул неполный список | Часть камер могла исчезнуть | Успешный legacy-ответ дополняет отсутствующие UID |
| Оба API недоступны | Токены не обновляются | Сохранить runtime и last-known-good; retry с backoff |
| Bearer Token истёк | Новые streamer-токены недоступны | Явный unhealthy и команда замены токена; секрет не логировать |
| JWT не содержит `exp` | Нельзя вычислить точный refresh | Обновлять раз в четыре часа |
| `streamerUrl` отсутствует/опасен | Нельзя доверять записи камеры | Пропустить дефектную запись, сохранить валидные камеры; если валидных нет — попробовать fallback и оставить прежний LKG |
| PATCH/probe одной камеры не прошёл | Новая конфигурация этой камеры отклоняется | Вернуть её прежние upstream и media profile, не менять LKG, повторить отдельно |
| go2rtc перезапущен | Runtime-streams исчезли | Controller повторно применяет LKG и свежие sources |
| Повреждён state JSON | Потеря стабильного mapping | Не перезаписывать файл; использовать резервную копию и аварийный статус |
| Неровные DTS H.264 | Зелёный экран или зависание клиента | Ленивый H.264 CFR; для стабильного источника разрешён `copy` |
| Слишком высокая CPU при просмотре | Сервер не успевает кодировать 1080p | Использовать URL 1280x720/640x360; не открывать разные variants одновременно |
| Аудиокодек не принят SprutHub | Видео есть, звука нет | PCMA по умолчанию, затем PCMU/AAC/copy; учитывать beta-ограничения SprutHub |
| Snapshot временно недоступен | Нет превью, RTSP не затронут | HTTP 502/503, ограничение параллелизма и повтор клиента |
| Камера исчезла из API | Старый endpoint остаётся, но upstream истечёт | Пометить отсутствующей; не переиспользовать её имя автоматически |
| Порт 8554 занят | RTSP не запускается | Явная ошибка Compose; поддержать настраиваемый host-порт |
| MQTT broker недоступен | Кнопки недоступны, видео продолжает работать | Exponential reconnect; retained catalog повторяется после подключения |
| Одна access-категория изменилась | Часть кнопок остаётся last-known | Независимые GET, partial snapshot и отдельный retry |
| Повтор MQTT QoS 1 | Риск повторного открытия | Duplicate detection, ограниченная очередь и cooldown до provider call |

## Проверка без Docker

- Unit-тесты всех чистых преобразований и расчёта времени.
- HTTP contract-тесты с поддельным transport для обоих форматов API, pagination, merge/fallback и ошибок.
- Тесты клиента go2rtc с локальным mock HTTP server, включая Basic Auth и URL encoding.
- Локальный mock RTSP server для авторизованных `OPTIONS`/`DESCRIBE`, без получения реального видео.
- Локальный Basic-auth snapshot server и проверка JPEG proxy без обращения к камере.
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
- Обработка звонков и двустороннего аудио; для них сохранён отдельный bounded context.
