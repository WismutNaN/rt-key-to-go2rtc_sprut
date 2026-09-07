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
- Видео всегда использует copy template с demuxer time base; по умолчанию аудио отсутствует.
- DTS игнорируется только при наличии PTS, а выходные пакеты отправляются без дополнительного накопления.
- Полный source не попадает в обычный лог.

## Намеренно НЕ обрабатывает

- Проверку фактического кодека потока без подключения к камере.
- Refresh токена.

## Заметки для агента

> По умолчанию формируется
> `#input=rtkey_http#video=rtkey_h264_copy#raw=rtkey_low_latency`. FFmpeg только
> перепаковывает H.264, сохраняет demuxer time base и сразу сбрасывает готовые
> пакеты в go2rtc. Producer используется лениво —
> только при наличии consumer. Допустимость hostname проверяет Rostelecom adapter до
> создания `SecretUrl`.
