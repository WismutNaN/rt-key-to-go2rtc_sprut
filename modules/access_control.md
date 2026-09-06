# Модуль: Управление доступом

**Ответственность**: обнаруживает домофоны и шлагбаумы Ростелекома и безопасно передаёт одноразовую команду открытия из MQTT SprutHub.
**Расположение**: `src/rtkey_gateway/domain/access.py`, `application/access_control.py`, `infrastructure/rtkey/access_control.py`, `infrastructure/mqtt_access.py`

## Публичный интерфейс

| Символ | Тип | Описание |
|---|---|---|
| `AccessPoint` | entity | Точка доступа с provider ID, видом, title и необязательным camera ID |
| `AccessCatalogSnapshot` | value object | Частичный или полный подтверждённый снимок категорий API |
| `AccessControlProviderPort` | protocol | Получение каталога и одноразовая команда открытия |
| `AccessEventPort` | protocol | Публикация устройств и получение команд без знания MQTT в application layer |
| `AccessControlService` | use case | Refresh, проверка команды, cooldown и вызов provider |
| `RtKeyAccessControl` | adapter | `intercom`, `barrier` и `POST .../{id}/open` |
| `MqttAccessEvents` | adapter | Retained discovery, reconnect, momentary switch и anti-replay |
| `SprutHubAccessTemplate` | adapter DTO | Один составной шаблон со статически именованными Switch services |

## Зависимости

| Модуль | Что использует |
|---|---|
| Shared kernel | `AccessTokenSource`, `Clock`, typed errors |
| JSON access state | Стабильный MQTT key и last-known каталог |
| SprutHub | Встроенный MQTT broker и один сгенерированный составной шаблон |

## Инварианты

- Provider ID никогда напрямую не становится MQTT-топиком; применяется стабильный безопасный key с hash.
- Открыть можно только `present`-устройство из последнего подтверждённого каталога.
- Retained-команды игнорируются, `ON` никогда не сохраняется retained, `OFF` не вызывает provider.
- Все команды сериализованы одной очередью и ограничены cooldown по устройству.
- Частичный отказ одной категории API не удаляет last-known устройства другой категории.
- Выключенный `ACCESS_CONTROL=off` не создаёт MQTT client и не обращается к access API.
- Каждая Switch service называется provider title; только дубли получают стабильный suffix.
- Retained `access/catalog` обнаруживает составное устройство после публикации состояний кнопок.

## Намеренно НЕ обрабатывает

- Состояние замка или подтверждение физического открытия: endpoint сообщает только результат принятия команды.
- Входящие звонки, двустороннее аудио и несколько реле одного устройства.
- Публичный HTTP endpoint открытия.

## Заметки для агента

> Открытие является необратимой командой. При расширении нельзя принимать произвольный provider ID из внешнего топика, сохранять `ON` retained или объединять команду с состоянием камеры. Новый API должен реализовать существующий port и возвращать нормализованный `AccessCatalogSnapshot`.
