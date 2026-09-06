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
- варианты `source`, `1280x720` и `640x360`;
- ленивую обработку: FFmpeg работает только пока есть зритель или snapshot-запрос.
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

Рекомендуемый явный профиль:

```bash
./install.sh --server-ip 192.168.1.50 \
  --audio pcma --video h264 --fps 30 \
  --resolutions source,1280x720,640x360 \
  --probe-workers 1 --snapshot-workers 2
```

### Добавление кнопок открытия в SprutHub

Управление доступом выключено по умолчанию. Для включения:

1. Включите встроенный MQTT-брокер SprutHub, задайте логин и пароль. Инструкция:
   [SprutHub Wiki](https://wiki.spruthub.ru/Как_включить_MQTT_брокер_в_Sprut.hub).
2. Создайте в SprutHub MQTT-контроллер с адресом `localhost` и портом `44444`:
   [инструкция](https://wiki.spruthub.ru/Создание_контроллера_MQTT).
3. В каталоге SprutHub выберите MQTT и импортируйте
   [`spruthub/rtkey_access.json`](spruthub/rtkey_access.json).
4. Запустите установку, указав LAN IP самого SprutHub и логин брокера:

```bash
./install.sh --server-ip 192.168.1.50 \
  --access-control mqtt \
  --mqtt-host 192.168.1.20 \
  --mqtt-user rtkey
```

Пароль MQTT будет запрошен без вывода на экран. После установки перезапустите
MQTT-контроллер SprutHub или запустите поиск устройств. Домофоны и шлагбаумы
появятся как переключатели `RT Key access`; переименуйте их по соответствию,
которое напечатает установщик и команда `./manage.sh access`.

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
RTSP URL:
rtsp://spruthub:<generated-password>@192.168.1.50:8554/podezd
Snapshot URL:
http://spruthub:<generated-password>@192.168.1.50:8080/snapshot/podezd.jpg

Resolution: 1280x720
RTSP URL:
rtsp://spruthub:<generated-password>@192.168.1.50:8554/podezd_1280x720
Snapshot URL:
http://spruthub:<generated-password>@192.168.1.50:8080/snapshot/podezd_1280x720.jpg
==========================================
```

В SprutHub добавьте **один** RTSP-вариант каждой физической камеры и
соответствующий snapshot URL. ONVIF не нужен. Все URL можно повторно
показать командой `./manage.sh show`.

## Разрешение и нагрузка

`source` сохраняет исходное разрешение. `1280x720` и `640x360` снижают нагрузку
на encoder во время просмотра, но входной 1080p всё равно нужно декодировать.
Начните с `1280x720`; для слабого CPU попробуйте также `--fps 15`.

Каждый открытый вариант запускает отдельную обработку. Не добавляйте все
три разрешения одной камеры в SprutHub: его snapshot polling создаст лишнюю нагрузку.

## Аудио

По умолчанию AAC-LC из upstream преобразуется в более совместимый с RTSP формат
`PCMA`. Доступны `pcma`, `pcmu`, `aac`, `copy`, `none`. Если SprutHub видит кодек,
но не показывает звук, проверьте ту же RTSP-ссылку в VLC. Звук в VLC при
его отсутствии в SprutHub означает ограничение RTSP-поддержки SprutHub.

## Управление

```bash
./manage.sh show          # RTSP and snapshot URLs
./manage.sh access        # MQTT settings and access device mapping
./manage.sh status        # containers and camera state
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
