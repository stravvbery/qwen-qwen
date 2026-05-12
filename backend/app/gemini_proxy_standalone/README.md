# Gemini API Proxy с автоматической ротацией ключей

## Что это

Автономный модуль-прокси для Google Gemini API с автоматической ротацией API-ключей.
Позволяет использовать несколько ключей одновременно, распределяя нагрузку между ними
и автоматически переключаясь на следующий ключ при получении ошибки rate limit (429)
или серверной ошибки (500+).

Модуль не зависит от остальных компонентов приложения и может быть интегрирован позже.

> **Примечание:** Этот модуль (`gemini_proxy_standalone`) существует отдельно от
> `backend/app/gemini_proxy.py`, который уже используется в основном приложении.
> Данный модуль предназначен для будущей интеграции или использования как
> самостоятельной библиотеки.

## Как работает

### Ротация ключей (Round-Robin)

При каждом запросе выбирается следующий доступный ключ по кругу. Если текущий ключ
получает ошибку, он автоматически отключается на период cooldown, и запрос
повторяется со следующим ключом.

### Состояния ключей

Каждый ключ может находиться в одном из трех состояний:

| Состояние | Описание |
|-----------|----------|
| `HEALTHY` | Ключ активен и доступен для запросов |
| `RATE_LIMITED` | Ключ получил 429 ошибку, на cooldown (по умолчанию 60 сек) |
| `ERROR` | Ключ получил серверную ошибку (500+), на cooldown (по умолчанию 300 сек) |

### Автоматическое восстановление

После истечения периода cooldown ключ автоматически переводится обратно в состояние
`HEALTHY` и снова участвует в ротации. Проверка происходит при каждом запросе на
получение ключа.

### Обработка ошибок

- **HTTP 429** - ключ помечается как `RATE_LIMITED`, запрос повторяется со следующим ключом
- **HTTP 500, 502, 503** - ключ помечается как `ERROR`, запрос повторяется
- **HTTP 403** - ключ помечается как `RATE_LIMITED` (часто означает исчерпание квоты)
- **Другие ошибки (4xx)** - считаются не-ретрайабельными, выбрасывается исключение

## Возможности

- Поддержка streaming и non-streaming ответов
- Конвертация сообщений из формата OpenAI в формат Gemini
- Встроенный инструмент `google_search` для grounding
- Полная асинхронность (httpx async)
- Диагностика состояния ключей

## Конфигурация

### Параметры инициализации

```python
from backend.app.gemini_proxy_standalone import GeminiKeyRotationProxy

proxy = GeminiKeyRotationProxy(
    api_keys=["key1", "key2", "key3"],          # Список API-ключей (обязательно)
    rate_limit_cooldown=60.0,                    # Cooldown при 429 (секунды)
    server_error_cooldown=300.0,                 # Cooldown при 500+ (секунды)
    timeout=120.0,                               # Общий таймаут запроса (секунды)
    connect_timeout=15.0,                        # Таймаут подключения (секунды)
    default_model="gemini-2.0-flash",            # Модель по умолчанию
    enable_google_search=True,                   # Включить google_search tool
)
```

### Формат ключей

Ключи берутся из Google AI Studio (https://aistudio.google.com/app/apikey).
Передаются как обычные строки в списке.

## Примеры использования

### Non-streaming запрос

```python
import asyncio
from backend.app.gemini_proxy_standalone import GeminiKeyRotationProxy

async def main():
    proxy = GeminiKeyRotationProxy(
        api_keys=["AIza...", "AIza...", "AIza..."]
    )

    messages = [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Explain quantum computing in simple terms."},
    ]

    response = await proxy.generate(messages, temperature=0.7)
    print(response)

asyncio.run(main())
```

### Streaming запрос

```python
import asyncio
from backend.app.gemini_proxy_standalone import GeminiKeyRotationProxy

async def main():
    proxy = GeminiKeyRotationProxy(
        api_keys=["AIza...", "AIza...", "AIza..."]
    )

    messages = [
        {"role": "user", "content": "Write a short poem about Python."},
    ]

    async for chunk in proxy.stream(messages):
        print(chunk, end="", flush=True)
    print()

asyncio.run(main())
```

### Проверка состояния ключей

```python
status = proxy.get_status()
for key_info in status:
    print(
        f"Key ...{key_info['key_suffix']}: "
        f"{key_info['status']}, "
        f"requests={key_info['request_count']}, "
        f"errors={key_info['error_count']}"
    )
```

## Как интегрировать в основное приложение

### 1. Добавить конфигурацию

В `backend/app/config.py` добавить настройку со списком ключей:

```python
gemini_proxy_keys: list[str] = []  # Заполняется из env GEMINI_PROXY_KEYS (через запятую)
```

### 2. Создать экземпляр при старте

В `backend/app/main.py` или отдельном файле зависимостей:

```python
from backend.app.gemini_proxy_standalone import GeminiKeyRotationProxy
from backend.app.config import settings

gemini_proxy = GeminiKeyRotationProxy(
    api_keys=settings.gemini_proxy_keys,
    rate_limit_cooldown=60.0,
    server_error_cooldown=300.0,
)
```

### 3. Использовать в роутах

```python
from fastapi import APIRouter

router = APIRouter()

@router.post("/api/gemini/chat")
async def gemini_chat(request: ChatRequest):
    response = await gemini_proxy.generate(request.messages)
    return {"content": response}
```

### 4. Добавить эндпоинт диагностики (опционально)

```python
@router.get("/api/gemini/status")
async def gemini_status():
    return gemini_proxy.get_status()
```

## Зависимости

- Python 3.10+
- httpx (уже установлен в проекте)
