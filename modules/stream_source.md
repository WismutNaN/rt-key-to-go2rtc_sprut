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
- Видео всегда `copy`; меняется только режим аудио.
- Полный source не попадает в обычный лог.

## Намеренно НЕ обрабатывает

- Проверку фактического кодека потока без подключения к камере.
- Refresh токена.

## Заметки для агента

> По умолчанию формируется `#video=copy#audio=copy`. Решение о режиме принимает отдельная audio policy. Для AAC/PCMA/PCMU go2rtc запускает FFmpeg-транскодирование только аудио. Допустимость hostname проверяет Rostelecom adapter до создания `SecretUrl`.
