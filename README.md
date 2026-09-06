# Rostelecom Key to RTSP/Snapshot for SprutHub

Шлюз публикует все камеры аккаунта «Ростелеком Ключ» как постоянные
RTSP-потоки и JPEG snapshot URL. Опционально он добавляет домофоны и
шлагбаумы в SprutHub через MQTT. Временные токены камер обновляются без
перезапуска RTSP-сервера.

> Интеграция неофициальная. Используйте её только для своих камер.

## Что вы получите

- стабильные имена камер, закреплённые за camera UID;
- RTSP с отдельным логином и паролем;
- JPEG snapshot URL с той же авторизацией;
- `source` без декодирования и перекодирования видео на сервере;
- лёгкие JPEG snapshots с настраиваемым кэшем;
- ленивую обработку: upstream работает только пока есть зритель или новый snapshot;
- кнопки открытия доступных домофонов и шлагбаумов без дополнительного контейнера.

## Требования

- Linux `amd64` или `arm64` в одной локальной сети со SprutHub;
- Docker Engine и Compose plugin (`docker compose`);
- Authorization token от «Ростелеком Ключ».

### Установка Docker

Для постоянного сервера установите Docker Engine и Compose plugin по
[официальной инструкции](https://docs.docker.com/engine/install/). Быстрый способ для
тестового/домашнего Linux-сервера:

```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker "$USER"
```

Перевойдите в систему заново и проверьте:

```bash
docker version
docker compose version
```

## Как получить Authorization token

1. Откройте <https://key.rt.ru/main/pwa/dashboard> и войдите в аккаунт.
2. Нажмите `F12` и откройте вкладку `Network` / `Сеть`.
3. Введите `barrier` в строке поиска.
4. Откройте GET-запрос и найдите `Headers` → `Request Headers` → `Authorization`.
5. Скопируйте всё значение. Префикс `Bearer` можно оставить.

## Быстрый старт

```bash
git clone https://github.com/WismutNaN/rt-key-to-go2rtc_sprut.git
cd rt-key-to-go2rtc_sprut
./install.sh --server-ip 192.168.1.50
```

Установщик запросит token, создаст пароль, запустит два контейнера и
напечатает все ссылки. `--server-ip` — LAN IP этого Docker-сервера;
его можно не указывать, если автоопределение работает верно.

Установщик всегда включает стабильный малонагруженный профиль: исходный H.264
передаётся без декодирования и кодирования, аудио отключено. Экспериментальные
профили разрешения в обычной установке не создаются.

### Добавление кнопок открытия в SprutHub

Управление доступом выключено по умолчанию. Для включения:

1. Включите встроенный MQTT-брокер SprutHub, задайте логин и пароль. Инструкция:
   [SprutHub Wiki](https://wiki.spruthub.ru/Как_включить_MQTT_брокер_в_Sprut.hub).
2. Создайте в SprutHub MQTT-контроллер с адресом `localhost` и портом `44444`:
   [инструкция](https://wiki.spruthub.ru/Создание_контроллера_MQTT).
3. Запустите установку, указав LAN IP самого SprutHub и логин брокера:

```bash
./install.sh --server-ip 192.168.1.50 \
  --access-control mqtt \
  --mqtt-host 192.168.1.20 \
  --mqtt-user rtkey
```

Пароль MQTT будет запрошен без вывода на экран. После обнаружения точек установщик
создаст каталог `generated/spruthub-access-<date>/` с отдельным JSON-файлом для
каждого места. Импортируйте **все** эти файлы в каталог MQTT SprutHub, перезагрузите
шаблоны, включите контроллер и выполните поиск/сопряжение устройств.

Название места от Ростелекома статически записывается и в устройство, и в его
кнопку-переключатель. Поэтому дополнительный сценарий и ручное переименование не
нужны. Если названия совпадают, генератор добавляет к ним разные короткие стабильные
идентификаторы. Список соответствий повторно показывает `./manage.sh access`, а
новый набор файлов создаёт `./manage.sh access-templates`.

Если ранее импортировался `rtkey_access.json` или `rtkey_access_v2.json`, сначала
остановите MQTT-контроллер и удалите старый шаблон вместе с созданными им
устройствами. Затем импортируйте новый набор. Имена файлов зависят от содержимого,
поэтому SprutHub не примет обновлённый шаблон за старую кэшированную версию.

Открытие выполняется только при команде `ON`. Через две секунды переключатель
автоматически возвращается в `OFF`; команда `OFF` ничего не делает. Сохранённая
в брокере команда не может открыть дверь после переподключения. Дубликаты MQTT
и повторные команды ограничены дополнительными проверками и интервалом в пять секунд.

Отключить функцию можно повторной установкой:

```bash
./install.sh --access-control off
```

В выключенном режиме контроллер не обращается к API домофонов и не подключается
к MQTT. Во включённом режиме медиапотоки также не запускаются: добавляется лишь
одно MQTT-соединение, два редких запроса каталога и POST непосредственно при
нажатии.

Пример вывода. Все собственные сообщения и подписи печатаются по-английски;
название камеры выводится в исходном виде, как его вернул провайдер:

```text
==========================================
SprutHub camera connection data
==========================================
Username: spruthub
Password: <generated-password>

Camera: Подъезд [camera-uid]
Stream name: podezd
Resolution: source
Video mode: copy
Audio: disabled
RTSP URL:
rtsp://spruthub:<generated-password>@192.168.1.50:8554/podezd
Snapshot URL:
http://spruthub:<generated-password>@192.168.1.50:8080/snapshot/podezd.jpg
==========================================
```

В SprutHub добавьте **один** RTSP-вариант каждой физической камеры и
соответствующий snapshot URL. ONVIF не нужен. Все URL можно повторно
показать командой `./manage.sh show`.

## Разрешение и нагрузка

`source + video=copy` сохраняет исходное разрешение и H.264 без video/audio
decode/encode. Это минимальная нагрузка на сервер и рекомендуемый режим для
SprutHub.

Уменьшение разрешения не предлагается: оно потребовало бы постоянно декодировать,
масштабировать и снова кодировать H.264. Это уменьшило бы LAN-трафик, но повысило
нагрузку на Docker-сервер. Snapshot декодирует только один keyframe и кэшируется
на 30 секунд (`--snapshot-cache`).

### Переход с прежнего 720p-профиля

Повторная установка автоматически удалит прежний экспериментальный media-профиль.
После неё замените в SprutHub URL с `_1280x720` на URL без суффикса:

```bash
git pull
./install.sh
./manage.sh show
```

## Аудио

В поддерживаемом профиле аудио намеренно отключено. SprutHub принимал PCMA/PCMU,
но не предоставлял управление звуком, а второй медиатрек и его перекодирование
ухудшали восстановление нестабильного потока. Поэтому установщик показывает
только рабочий video-only вариант. Внутренняя media policy сохраняет отдельные
аудиорежимы для будущего возврата функции после проверки совместимости.

## Управление

```bash
./manage.sh show          # RTSP and snapshot URLs
./manage.sh access        # MQTT settings and access device mapping
./manage.sh access-templates # create named SprutHub JSON templates
./manage.sh status        # containers and camera state
./manage.sh media-status  # one-time CPU, memory, and process counters
./manage.sh check-streams # active test of every stream
./manage.sh refresh       # refresh camera data without restarting go2rtc
./manage.sh logs          # controller logs
./manage.sh logs-media    # FFmpeg diagnostics; URLs may contain tokens
./manage.sh set-token     # replace an expired Authorization token
./manage.sh down
./manage.sh up
```

Измените параметры повторным запуском `install.sh` с нужными флагами.
Скрипт сохраняет credentials и найденные имена камер.

## Безопасность и ограничения

- RTSP `8554` и snapshot HTTP `8080` защищены Basic Auth, но трафик не шифруется.
  Не публикуйте эти порты в Интернет; в LAN ограничьте firewall IP-адресом SprutHub.
- API go2rtc `1984` не публикуется на Docker-host.
- Authorization token может быть отозван провайдером; замените его через
  `./manage.sh set-token`.
- Открытие использует неофициальный API Ростелекома и может зависеть от региона
  и прав аккаунта. Не публикуйте MQTT `44444` в Интернет.
- Обычный healthcheck не запускает media. `check-streams` запускает все потоки
  на время проверки.

Подробная диагностика: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).

## Удаление

```bash
./uninstall.sh         # keep credentials and state
./uninstall.sh --purge # also remove credentials and Docker volume
```
