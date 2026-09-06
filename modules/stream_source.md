# Модуль: Построитель source

**Ответственность**: преобразует доменный `CameraFeed` и `MediaProfile` в безопасный ffmpeg source конкретного адаптера go2rtc.
**Расположение**: `src/rtkey_gateway/infrastructure/go2rtc_source.py`

## Публичный интерфейс

| Символ | Тип | Описание |
|---|---|---|
| `build_go2rtc_source()` | функция | Добавляет ffmpeg и selectors из `MediaProfile` |
| `redact_source()` | функция | Удаляет token из диагностического текста |

## Зависимости

| Модуль | Что использует |
|---|---|
| `domain.video` | `CameraFeed` с уже нормализованным upstream URL |
| `domain.media` | `MediaProfile` с режимами видео и аудио |
| Python `urllib.parse` | Разбор URL и корректное query encoding |

## Инварианты

- Полученный upstream URL не изменяется и не разбирается повторно.
- Видео использует стабильный H.264 template или `copy`; аудио выбирается независимо.
- Optional width/height передаются штатными параметрами go2rtc и всегда имеют H.264 output.
- Полный source не попадает в обычный лог.

## Намеренно НЕ обрабатывает

- Проверку фактического кодека потока без подключения к камере.
- Refresh токена.

## Заметки для агента

> По умолчанию формируется
> `#input=rtkey_http#video=rtkey_h264_stable#audio=pcma`. FFmpeg template
> нормализует timestamps в CFR и используется go2rtc лениво — только при наличии
> consumer. Для стабильной камеры `video=copy` выключает video decode/encode даже
> во время просмотра. Допустимость hostname проверяет Rostelecom adapter до
> создания `SecretUrl`.
