# Модуль: Shared kernel

**Ответственность**: содержит только технически общие контракты, которые могут понадобиться независимым bounded contexts.
**Расположение**: `src/rtkey_gateway/shared/ports.py`, `src/rtkey_gateway/errors.py`

## Публичный интерфейс

| Символ | Тип | Описание |
|---|---|---|
| `AccessTokenSource` | Protocol | Возвращает Bearer Token без знания файла, vault или механизма обновления |
| `Clock` | Protocol | Даёт wall-clock время для JWT `exp`, audit и сроков сессий |
| `GatewayError` и наследники | exceptions | Типизированная классификация auth/transport/schema/state/media ошибок |

## Зависимости

| Модуль | Что использует |
|---|---|
| Python stdlib | Только `typing.Protocol` и базовые exceptions |

## Инварианты

- Shared kernel не содержит `Camera`, `Device`, endpoint, JSON-схемы или команды открытия.
- Bounded context может использовать эти ports, не импортируя application layer другого контекста.
- Конкретный файловый token source и системные часы остаются infrastructure adapters.

## Намеренно НЕ обрабатывает

- Refresh основного Bearer Token.
- Унификацию ID камер, домофонов, дверей и звонков.
- HTTP transport конкретного провайдера.

## Заметки для агента

> Добавлять сюда тип можно только после появления минимум двух реальных потребителей с одинаковой семантикой. Сходное имя поля во внешних JSON не является основанием для расширения shared kernel.
