# Документация проекта RT Key → go2rtc для SprutHub

Проект превращает облачные камеры «Ростелеком Ключ» с временными токенами в постоянные RTSP-потоки с авторизацией. Опциональный MQTT-модуль публикует кнопки домофонов и шлагбаумов в SprutHub без дополнительного контейнера.

Проект предназначен для одного владельца домашней инфраструктуры. Он не является официальной интеграцией Ростелекома и не может автоматически восстановить истёкший основной Bearer Token.

## Быстрый старт

```text
git clone <адрес-репозитория>
cd rt-key-to-go2rtc_sprut
./install.sh
```

Установщик скрыто запрашивает Bearer Token, генерирует пароли, запускает `docker compose` и выводит для каждой камеры постоянную ссылку вида:

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

## Навигация

| Документ | Назначение |
|---|---|
| [PLAN.md](PLAN.md) | Фазы реализации, тесты, миграция и rollback |
| [ARCHITECTURE.md](ARCHITECTURE.md) | Компоненты, потоки данных, интерфейсы и режимы отказа |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | Первый запуск, проверка потоков, аудио и восстановление |
| [ADR-0001](adr/0001-stack.md) | Выбор стека и Docker-схемы |
| [ADR-0002](adr/0002-state.md) | Хранение соответствий камер и last-known-good |
| [ADR-0003](adr/0003-concurrency.md) | Модель конкурентности и планирование обновлений |
| [ADR-0004](adr/0004-errors.md) | Ошибки, повторы и деградация |
| [ADR-0005](adr/0005-api-isolation.md) | Изоляция API go2rtc в Docker |
| [ADR-0006](adr/0006-domain-boundaries.md) | DDD-lite, направленные зависимости и будущие контексты |
| [ADR-0007](adr/0007-lazy-compatible-media.md) | Ленивый медиатракт и профиль совместимости SprutHub |
| [ADR-0008](adr/0008-mqtt-access-control.md) | Opt-in управление доступом через MQTT SprutHub |

## Текущий статус

Docker-вариант реализован полностью. По реальным RTSP-потокам подтверждены H.264,
AAC-LC 48 kHz mono, частые keyframes и нестабильные DTS исходного fragmented MP4.
Видео проходит без декодирования; аудио в стабильном профиле отключено, опасная
подмена timestamps системным временем удалена. На машине разработки выполнены только
офлайн-тесты Python и статические проверки; Docker по условию владельца не
запускался. MQTT-кнопки управления доступом также реализованы, но требуют
приёмки с реальным аккаунтом и broker SprutHub на целевом Linux-сервере.
