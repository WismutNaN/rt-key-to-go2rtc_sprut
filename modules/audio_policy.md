# Модуль: Политика media

**Ответственность**: независимо от Ростелеком API выбирает video/audio profile
для передачи или нормализации каждой камеры.
**Расположение**: `src/rtkey_gateway/domain/media.py`

## Публичный интерфейс

| Символ | Тип | Описание |
|---|---|---|
| `AudioMode` | enum | `copy`, `aac`, `pcma`, `pcmu`, `none` |
| `VideoMode` | enum | `copy` |
| `MediaResolution` | value object | Поддерживаемое значение `source` |
| `MediaVariant` | value object | Профиль единственного source-варианта |
| `MediaProfile` | dataclass | Неизменяемые video/audio mode и `video_fps` |
| `MediaPolicy` | class | Читает глобальные режимы и необязательные overrides по UID |
| `AudioPolicy` | alias | Совместимость расширений с прежним именем класса |
| `profile_for()` | метод | Возвращает эффективный media profile конкретной камеры |

## Зависимости

| Модуль | Что использует |
|---|---|
| `domain.video` | `CameraId` для per-camera override |

## Инварианты

- Значения по умолчанию — H.264 copy, 15 fps для opt-in encoder и PCMU.
- Вариант по умолчанию — только `source`; максимум четыре.
- Неизвестный режим завершает проверку конфигурации с понятной ошибкой до PATCH.
- Video/audio per-camera overrides независимы и имеют приоритет над глобальными.
- Любой масштабированный набор отклоняется до обновления runtime.
- Изменение media policy не меняет публичные URL или mapping UID → name.

## Намеренно НЕ обрабатывает

- Автоматическое определение совместимости SprutHub.
- Двустороннее аудио и backchannel.
- Анализ качества и синхронизации аудио.

## Заметки для агента

> `VIDEO_MODE=copy` не декодирует видео и является основным режимом. Input
> template генерирует отсутствующие PTS и сохраняет demuxer time base; подмена
> timestamp системным временем запрещена. `AUDIO_MODE=pcmu` соответствует
> предпочтению, которое SprutHub показал в диагностике. `none` остаётся fallback
> для камер с повреждённой аудиодорожкой.
