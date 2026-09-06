# Модуль: Клиент Ростелекома

**Ответственность**: реализует `VideoCatalogPort`, скрывая endpoint, схемы JSON и токены Ростелекома за anti-corruption layer.
**Расположение**: `src/rtkey_gateway/infrastructure/rtkey/video_catalog.py`

## Публичный интерфейс

| Символ | Тип | Описание |
|---|---|---|
| `NewCameraApiStrategy` | adapter | Новый endpoint, pagination и camelCase parser |
| `LegacyCameraApiStrategy` | adapter | Старый endpoint, pagination и snake_case parser |
| `FallbackVideoCatalog` | adapter | Объединяет успешные стратегии с приоритетом новой |
| `fetch_feeds()` | метод | Возвращает `list[CameraFeed]` либо типизированную ошибку |
| `decode_jwt_exp()` | функция | Читает `exp` из payload без проверки подписи и без роли аутентификации |

## Зависимости

| Модуль | Что использует |
|---|---|
| `UrllibTransport` | HTTP, TLS verification, timeout, запрет redirects и Bearer header |
| `application.ports` | Реализует `VideoCatalogPort` |
| `domain.video` | Создаёт только `CameraFeed`, `CameraId`, `SecretUrl` |

## Инварианты

- Новый API вызывается первым.
- Legacy вызывается максимум один раз за цикл и дополняет UID, которых нет в новом API.
- Pagination имеет верхнюю защитную границу и обнаруживает повтор страницы.
- Пустой успешный список отличим от неверной схемы.
- В доменную модель не попадает камера без UID, token или streamer URL.
- Host берётся из `streamerUrl`; adapter строит полный HTTPS live URL и URL-кодирует token.
- Поля конкретного API не пересекают границу adapter.
- Bearer Token никогда не входит в текст исключения или лог.

## Намеренно НЕ обрабатывает

- Получение нового Bearer Token.
- Выбор RTSP-имени камеры.
- Преобразование media URL в синтаксис source и PATCH go2rtc.

## Заметки для агента

> Новый endpoint использует `paging.limit`/`paging.offset` и поля `uid`, `streamerToken`, `streamerUrl`, `screenshotToken`. Legacy использует `limit`/`offset`, контейнер `data.items` и snake_case поля. Нормализатор должен принимать только явно поддержанные варианты структуры; нельзя считать произвольный пустой объект списком без камер.
