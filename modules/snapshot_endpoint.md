# Модуль: Snapshot endpoint

**Ответственность**: по авторизованному запросу возвращает один JPEG для
проверенной камеры, не публикуя общий API go2rtc.
**Расположение**: `src/rtkey_gateway/application/snapshot.py`,
`src/rtkey_gateway/interfaces/snapshot_http.py`

## Публичный интерфейс

| Символ | Тип | Описание |
|---|---|---|
| `GetCameraSnapshot` | application query | Разрешает только активный проверенный `StreamName` |
| `SnapshotHttpService` | inbound adapter | Basic-auth `GET /snapshot/<stream>.jpg` |
| `SnapshotGatewayPort` | Protocol | Получение JPEG без зависимости application от go2rtc |
| `Go2RtcMediaGateway.fetch_jpeg()` | outbound adapter | Внутренний `GET /api/frame.jpeg` с кешем |

## Зависимости

| Модуль | Что использует |
|---|---|
| `state_store` | Проверяет наличие активного last-known-good binding |
| `go2rtc_client` | Получает JPEG внутри Compose-сети |
| `domain.video` | Валидирует постоянный `StreamName` |

## Инварианты

- Snapshot использует существующий публичный copy producer.
- Декодируется только один keyframe; JPEG кэшируется на заданный интервал.
- Неизвестная, исчезнувшая или ещё не проверенная камера не запускает upstream.
- HTTP endpoint требует те же отдельные credentials, что и RTSP.
- Ответ ограничен 10 MiB и обязан иметь сигнатуру JPEG.
- Число одновременных генераций ограничено; общий API go2rtc не публикуется.

## Намеренно НЕ обрабатывает

- Архив изображений и постоянный polling.
- Изменение качества JPEG.
- Авторизацию основным Bearer Token Ростелекома.

## Заметки для агента

> Snapshot endpoint относится к inbound interface Video Gateway, а не к домену
> камер Ростелекома. При замене go2rtc меняется реализация `SnapshotGatewayPort`,
> но публичный URL и application query сохраняются.
