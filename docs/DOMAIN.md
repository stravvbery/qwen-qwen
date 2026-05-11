# Подключение домена `grebeshok.eu.cc`

Backend деплоится на Fly.io. Чтобы домен `grebeshok.eu.cc` (или
поддомен, например `chat.grebeshok.eu.cc`) указывал на приложение,
нужно один раз:

## 1. Получить IP-адреса приложения на Fly.io

После `fly deploy` назначь IP-адреса (если ещё нет):

```bash
fly ips list                    # посмотреть назначенные
fly ips allocate-v4 --shared    # бесплатный shared IPv4
fly ips allocate-v6             # бесплатный IPv6
```

В выводе будут две строки — IPv4 и IPv6. Запиши их.

## 2. Прописать DNS у регистратора (eu.org / freedns / Cloudflare и т.п.)

Открой панель управления DNS-зоной `grebeshok.eu.cc` и добавь:

### Вариант A — apex-домен `grebeshok.eu.cc`

| Тип    | Имя | Значение              | TTL  |
| ------ | --- | --------------------- | ---- |
| `A`    | `@` | `<IPv4 из fly ips>`   | 300  |
| `AAAA` | `@` | `<IPv6 из fly ips>`   | 300  |

### Вариант B — поддомен `chat.grebeshok.eu.cc`

Если основной домен уже занят (например, GitHub Pages), используй
поддомен:

| Тип     | Имя    | Значение                    | TTL  |
| ------- | ------ | --------------------------- | ---- |
| `CNAME` | `chat` | `grebeshok-chat.fly.dev`    | 300  |

> Замени `grebeshok-chat` на имя своего Fly-приложения, если меняешь.

## 3. Подключить домен в Fly и выпустить SSL

После того как DNS-записи прописаны (можно проверить `dig grebeshok.eu.cc`),
выполни на той машине, где залогинен `fly`:

```bash
fly certs add grebeshok.eu.cc
# или для поддомена:
fly certs add chat.grebeshok.eu.cc
```

Fly автоматически выпустит сертификат через Let's Encrypt. Статус:

```bash
fly certs show grebeshok.eu.cc
```

Должно стать `status = Ready` и `acme_alpn_configured = true`.

## 4. Обновить `ALLOWED_ORIGINS`

В `fly.toml` (или через `fly secrets set`) укажи, какие origin-ы
имеют право обращаться к API:

```bash
fly secrets set ALLOWED_ORIGINS="https://grebeshok.eu.cc"
```

После этого фронтенд на твоём домене будет работать с API без CORS-ошибок.

## Что я уже сделал

- Конфиг `fly.toml` готов, Dockerfile собирает frontend + backend в один образ.
- `/api/health` отдаёт 200 — Fly его использует как health check.
- SPA сервится с корня (`/`), API — с префиксом `/api`.

## Что нужно от тебя

1. Создать приложение на Fly.io (если ещё нет):
   ```bash
   fly auth login
   fly apps create grebeshok-chat
   fly volumes create grebeshok_data --region fra --size 1
   fly secrets set FIREWORKS_API_KEY=fw_...
   fly deploy
   ```
2. Назначить IPv4/IPv6 как описано выше.
3. Прописать DNS-записи у регистратора `eu.cc`.
4. Запустить `fly certs add grebeshok.eu.cc`.

Если хочешь, чтобы я сделал шаги 1–4 за тебя — нужен токен Fly
(`fly auth token`) как сикрет в Devin.
