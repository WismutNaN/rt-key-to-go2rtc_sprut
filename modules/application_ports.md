# Модуль: Application ports

**Ответственность**: задаёт узкие контракты, через которые use cases Video Gateway работают с внешним миром.
**Расположение**: `src/rtkey_gateway/application/ports.py`

## Публичный интерфейс

| Символ | Тип | Описание |
|---|---|---|
| `VideoCatalogPort` | Protocol | Возвращает нормализованные `CameraFeed` |
| `MediaGatewayPort` | Protocol | Проверяет готовность и upsert runtime-stream |
| `VideoStateRepository` | Protocol | Загружает и атомарно сохраняет состояние Video Gateway |
| `MediaProbePort` | Protocol | Возвращает доступность RTSP-сервера и проверенных потоков |

## Зависимости

| Модуль | Что использует |
|---|---|
| `domain.video` | `CameraFeed`, `CameraBinding`, `StreamName` |
| `domain.media` | `MediaProfile` |

`AccessTokenSource` и `Clock` находятся в [shared kernel](shared_kernel.md), потому что не принадлежат исключительно Video Gateway.

## Инварианты

- Каждый port соответствует одной внешней способности, а не конкретному продукту.
- Сигнатуры не содержат `requests.Response`, JSON dict или go2rtc query string.
- Application ports не импортируют infrastructure и interfaces.
- Изменение версии API Ростелекома требует нового adapter, но не изменения use case.
- Открытие двери и звонки не добавляются методами в `VideoCatalogPort`.

## Намеренно НЕ обрабатывает

- Реализацию HTTP, JSON, filesystem и Docker.
- Контракты будущих bounded contexts до начала их реализации.

## Заметки для агента

> Не создавать «универсальный provider» с десятками optional-методов. Для Access Control появится отдельный port, для Intercom Calls — отдельные signaling/media ports. Общим может быть только `AccessTokenSource` и низкоуровневый HTTP transport внутри infrastructure.
