# Ростелеком Ключ → RTSP для SprutHub

Проект автоматически находит все камеры аккаунта «Ростелеком Ключ» и публикует их как постоянные RTSP-потоки с логином и паролем. Временные `streamer_token` обновляются перед реальным JWT `exp` через API go2rtc — без перезапуска RTSP-сервера.

Интеграция неофициальная. Используйте её только для камер и устройств, к которым у вас есть законный доступ.

## Что исправлено

- Новый camera API используется первым, старый остаётся fallback.
- Адрес медиасервера извлекается из `streamerUrl`, `live-vdk4` не зашит.
- Понятное имя строится из `title` и навсегда закрепляется за UID камеры.
- Source меняется через `PATCH /api/streams`; go2rtc не перезапускается.
- Новый source проверяется через RTSP `DESCRIBE`; при ошибке возвращается полный last-known-good, включая аудиопрофиль.
- RTSP требует отдельные credentials SprutHub.
- API go2rtc защищён Basic Auth и не публикуется в локальную сеть.
- Версия go2rtc закреплена: `1.9.14`.
- Видео передаётся с `video=copy`; аудиорежим можно менять отдельно.

## Требования

- Linux-сервер `amd64` или `arm64` в одной локальной сети со SprutHub.
- Docker Engine и Compose plugin (`docker compose`).
- Bearer Token от «Ростелеком Ключ».

Сам проект не устанавливает Docker и не изменяет firewall.

## Быстрый старт

```bash
git clone https://github.com/WismutNaN/rt-key-to-go2rtc_sprut.git
cd rt-key-to-go2rtc_sprut
./install.sh
```

Если сервер не определил правильный LAN IP:

```bash
./install.sh --server-ip 192.168.1.50
```

Для автоматической установки:

```bash
ACCESS_TOKEN='eyJ...' ./install.sh --server-ip 192.168.1.50
```

Bearer Token сохраняется отдельно от `.env` в закрытом каталоге
`secrets/rtkey_access_token`. Каталог имеет права `0700`; файл доступен
controller только как Compose file secret и не попадает ни в окружение
контейнера, ни в Git или Docker build context. Установщик автоматически
перенесёт токен из `.env`, если обновляется более ранняя версия проекта.
Чтобы получить токен:

1. Откройте <https://key.rt.ru/main/pwa/dashboard> и войдите.
2. Откройте `F12` → `Network`.
3. Найдите запрос `barrier`.
4. Скопируйте значение заголовка `Authorization` после слова `Bearer`.

После первого успешного обнаружения установщик напечатает все камеры:

```text
==========================================
Данные камер для SprutHub
==========================================
Логин:  spruthub
Пароль: <случайный пароль>

Подъезд [camera-uid]:
rtsp://spruthub:<пароль>@192.168.1.50:8554/podezd

Двор [camera-uid]:
rtsp://spruthub:<пароль>@192.168.1.50:8554/dvor
==========================================
```

Эти URL добавляются в SprutHub как обычные RTSP-камеры. ONVIF не требуется.

## Управление

```bash
./manage.sh show       # повторно показать RTSP-ссылки
./manage.sh status     # контейнеры и безопасный статус камер
./manage.sh logs       # безопасные логи controller
./manage.sh logs-media # go2rtc/FFmpeg; перед публикацией удалить токены
./manage.sh refresh    # обновить камеры, не останавливая go2rtc
./manage.sh set-token  # заменить истёкший Bearer Token
./manage.sh down       # остановить контейнеры, сохранив состояние
./manage.sh up         # запустить снова
```

Обычное удаление сохраняет секреты и состояние:

```bash
./uninstall.sh
```

Полное удаление, включая Docker volume и credentials:

```bash
./uninstall.sh --purge
```

## Аудио

По умолчанию используется `AUDIO_MODE=copy`: исходные видео и аудио передаются без перекодирования. Если SprutHub показывает видео без звука, измените в `.env` только эту строку:

```dotenv
AUDIO_MODE=aac
```

Допустимы `copy`, `aac`, `pcma`, `pcmu`, `none`. Затем выполните:

```bash
./manage.sh refresh
```

`video=copy` сохраняется при любом аудиорежиме. Для будущих индивидуальных настроек камер предусмотрен `AUDIO_OVERRIDES_JSON`, например:

```dotenv
AUDIO_OVERRIDES_JSON={"camera-uid-1":"aac","camera-uid-2":"pcma"}
```

## Устройство

Используются два контейнера:

```text
Ростелеком API → controller → внутренний API go2rtc → RTSP :8554 → SprutHub
                         PATCH /api/streams
```

- `controller` отвечает за API-версии, токены, постоянные имена, проверку upstream и состояние.
- `go2rtc` отвечает только за media/RTSP.
- Порт `1984` отсутствует в `ports` Compose и недоступен устройствам LAN.
- Наружу публикуется только `8554/tcp` с авторизацией.

Архитектура — модульный DDD-lite с ports/adapters. Изменение API Ростелекома изолировано в versioned strategies. Управление дверьми/шлагбаумами и звонки предусмотрены как отдельные будущие bounded contexts, а не как методы видеоклиента.

Подробности:

- [Архитектура](docs/ARCHITECTURE.md)
- [План миграции](docs/PLAN.md)
- [Первый запуск и диагностика](docs/TROUBLESHOOTING.md)
- [ADR по доменным границам](docs/adr/0006-domain-boundaries.md)

## Ограничения

- Основной Bearer Token нельзя надёжно обновить автоматически из-за неофициального API и возможной captcha.
- Фактическая совместимость аудиокодека проверяется на конкретной версии SprutHub.
- Первый реальный запуск и проверка RTSP выполняются на целевом Docker-сервере.
- `archive/` — отдельная legacy/experimental-утилита и не входит в новое Docker-развёртывание.
