# Grebeshok Chat — handoff для следующей Devin-сессии

> Этот файл — точка входа для новой сессии. Положи его в репо и пришли ссылку
> на него (или сам файл) новому Devin'у, чтобы он сразу понял контекст.
> Сгенерирован 2026-05-11.

## 1. Кратко: о чём проект

Личный AI-чат на Fireworks API для пользователя `grebeshok105`.
Стек: **FastAPI + SQLAlchemy (SQLite) + httpx** (бэк), **React 18 + Vite +
TypeScript + Tailwind** (фронт), сборка в **один Docker-образ**.

Цель: получить рабочий сайт-чат на собственном домене **`grebeshok.eu.cc`**
с 4 моделями Fireworks, историей чатов и стримингом, чтобы пользоваться лично.

## 2. Важные решения и выводы

- 4 модели зафиксированы на сервере (whitelist в `backend/app/routes.py`,
  массив `ALLOWED_MODELS`). Любая другая Fireworks-модель не сможет быть
  выбрана с фронта.
- Стриминг — через **Server-Sent Events**: `POST /api/chats/{id}/messages`
  отдаёт `text/event-stream` с событиями `meta`, `delta`, `title`, `done`,
  `error`. `reasoning_content` отделяется от `content`, фронт показывает его
  в сворачиваемой панели «Размышления».
- `FIREWORKS_API_KEY` никогда не уходит в браузер — фронт ходит только в
  `/api/*`, бэк проксирует в Fireworks. CORS закрывается через
  `ALLOWED_ORIGINS` на проде.
- На Gname у пользователя только сам домен и бесплатный DNS
  (`a.share-dns.com`, `b.share-dns.net`), хостинга нет. Поэтому деплой —
  на **Fly.io**, у Gname только прописать `A` + `AAAA` записи и `fly certs
  add grebeshok.eu.cc` для Let's Encrypt. Платный SSL у Gname ($14.70/yr)
  **не нужен**.
- Удаление чатов требует двойного клика, окно подтверждения **3 секунды**.
- Kimi K2.6 — reasoning-модель, первый токен может прийти через ~8–10 сек.
  Это не баг, UI пока показывает «Размышления».
- Ключ Fireworks `fw_XFLsDV3wyLJd4CbVkpc5ux` **засветился** в чате открытым
  текстом — перед продом обязательно ротейтнуть.

## 3. Ссылки, репо, файлы, команды

### Репозиторий
- GitHub: <https://github.com/grebeshok105/Web-API-for-qwen-and-qwen>
- Базовая ветка: `main` (PR #1 уже смержен)
- Текущая рабочая ветка: `devin/1778518970-deploy-fix`

### Ключевые файлы
- `backend/app/main.py` — FastAPI, CORS, lifespan-init БД, SPA с `/`,
  API с `/api/*`
- `backend/app/routes.py` — CRUD чатов, SSE-стрим, автозаголовок,
  `ALLOWED_MODELS`
- `backend/app/fireworks.py` — async-обёртка над `chat/completions` со
  стримингом
- `backend/app/models.py` — `Chat`, `Message` (есть поле `reasoning`)
- `frontend/src/App.tsx` — главный layout, роутинг (`/` и `/c/:id`)
- `frontend/src/lib/api.ts` — клиент API + SSE-парсер
- `Dockerfile` — multi-stage, один образ с фронтом и бэком
- `fly.toml` — конфиг Fly.io
- `docs/DOMAIN.md` — пошагово как подключить `grebeshok.eu.cc`
- `design-system.md` — токены тёмной темы
- `test-plan.md`, `test-report.md` — план и отчёт прошедшего UI-теста
- `.agents/skills/` — 27 SKILL.md из присланного `skills.zip`

### Команды локального запуска
```bash
# backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e .
export FIREWORKS_API_KEY=fw_...
uvicorn app.main:app --reload --port 8000

# frontend
cd ../frontend
npm install
npm run dev    # http://localhost:5173, проксирует /api → :8000

# или одной командой через Docker
docker build -t grebeshok-chat .
docker run -p 8080:8080 -e FIREWORKS_API_KEY=fw_... grebeshok-chat
```

### Команды деплоя (Fly.io)
```bash
fly auth login
fly apps create grebeshok-chat
fly volumes create grebeshok_data --region fra --size 1
fly secrets set FIREWORKS_API_KEY=fw_новый ALLOWED_ORIGINS=https://grebeshok.eu.cc
fly deploy
fly ips list                       # → выписать IPv4 и IPv6
fly certs add grebeshok.eu.cc
fly certs show grebeshok.eu.cc     # ждать status=Ready
```

В кабинете Gname (DNS Resolution):
- `A` запись: `@` → `<IPv4>`
- `AAAA` запись: `@` → `<IPv6>`

## 4. Что уже сделано

- [x] Распакован `skills.zip`, все SKILL.md лежат в `.agents/skills/`
- [x] Спроектирована и реализована вся архитектура (бэк + фронт + БД)
- [x] PR #1 «feat: Grebeshok Chat — личный чат-бот на Fireworks API»
      смержен в `main`
- [x] `Dockerfile` + `fly.toml` готовы, health-check на `/api/health`
- [x] `docs/DOMAIN.md` с инструкцией под `grebeshok.eu.cc`
- [x] Локальный UI-тест: **5 из 5** сценариев passed
  (`test-plan.md`/`test-report.md` в репо). Видео-запись и скриншоты
  отправлены пользователю
- [x] Бэк временно выставлен наружу через **pinggy tunnel** —
  `https://drryv-54-201-200-193.run.pinggy-free.link/`
  (живёт 60 минут, потом надо переподнять)
- [x] Запрошены два секрета у пользователя: `FLY_API_TOKEN`,
  `FIREWORKS_API_KEY_PROD` (на момент написания **не предоставлены**)

## 5. Что осталось сделать

1. **Получить от пользователя** новый Fireworks API key и Fly.io PAT
   (можно вместо Fly выбрать любой другой хостинг с Docker — Railway,
   Render, VPS).
2. `fly apps create grebeshok-chat` (или альтернатива на выбранном хосте).
3. `fly volumes create grebeshok_data --region fra --size 1` (для SQLite).
4. `fly secrets set FIREWORKS_API_KEY=… ALLOWED_ORIGINS=https://grebeshok.eu.cc`.
5. `fly deploy`, дождаться зелёного `/api/health`.
6. `fly ips allocate-v4 --shared && fly ips allocate-v6`, выписать оба IP.
7. **Пользователь** прописывает A/AAAA записи у Gname на эти IP.
8. `fly certs add grebeshok.eu.cc`, дождаться `status=Ready`.
9. Проверить открытие `https://grebeshok.eu.cc` в браузере, прогнать
   тот же тест-план уже на проде.
10. (опц) Установить pre-commit-хуки, добавить CI на GitHub Actions
    (сейчас 0 проверок), сконфигурировать бэкапы SQLite.

## 6. Предпочтения и правила пользователя

- Язык общения — **русский**.
- Пользователь — `grebeshok105` (GitHub).
- Домен принадлежит пользователю: `grebeshok.eu.cc`, регистратор **Gname**.
- На Gname **только домен + бесплатный DNS**, никакого хостинга, никакого
  cPanel. Полагаемся на внешний хостинг и DNS у Gname.
- Платный SSL у Gname не покупаем — Let's Encrypt бесплатно.
- Любые ключи (Fireworks, Fly) **никогда не коммитить** — только через
  `fly secrets` / окружение. Скомпрометированный ключ ротейтить.
- Пользователь хочет видеть прогресс в виде ссылок и работающего сайта,
  не длинных простыней текста.
- Английский в коммитах/коде ок, в общении — русский.
- PR-флоу: создавать PR через стандартный шаблон, не пушить в `main`
  напрямую.

## 7. Готовый prompt для новой сессии

```
Я — grebeshok105. Продолжи работу над моим личным AI-чатом на Fireworks API.

Репо: https://github.com/grebeshok105/Web-API-for-qwen-and-qwen
Главный документ контекста: SESSION_HANDOFF.md в корне репо — прочитай его
полностью перед действиями.

Стек: FastAPI + SQLite + httpx (бэк), React + Vite + TypeScript + Tailwind
(фронт), один Docker-образ, Fly.io как хостинг. Домен grebeshok.eu.cc
зарегистрирован на Gname, у Gname только бесплатный DNS, хостинга нет.

Сейчас нужно довести деплой до конца:
1. Я дам тебе FLY_API_TOKEN и новый FIREWORKS_API_KEY_PROD (запрашивай
   через `secrets` tool, не вписывай их в код).
2. Создай Fly-приложение `grebeshok-chat` в регионе fra, прицепи volume
   `grebeshok_data` под /data, выставь secrets, задеплой.
3. Пришли мне IPv4/IPv6 и точные значения для A/AAAA записей — я сам
   воткну их в кабинете Gname (DNS Resolution).
4. После того как я подтвержу, что записи прописаны, запусти
   `fly certs add grebeshok.eu.cc` и дождись status=Ready.
5. Открой https://grebeshok.eu.cc в браузере, прогони мини-тест-план из
   test-plan.md уже на проде, пришли мне скриншоты и короткий отчёт.

Общайся на русском, ключи не светить, PR-флоу через шаблон, в main не
пушить напрямую.
```

---

_Сгенерировано Devin-сессией <https://app.devin.ai/sessions/bd37abe098284ce1aa5b30c669f36a78>._
