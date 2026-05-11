# Grebeshok Chat

Personal AI chat web app powered by the [Fireworks AI](https://fireworks.ai)
API. Custom UI inspired by modern chat clients (Claude, ChatGPT) with chat
history persisted on the server.

Models available out of the box:

- `accounts/fireworks/models/deepseek-v4-pro` — DeepSeek V4 Pro (1M ctx)
- `accounts/fireworks/models/kimi-k2p6` — Kimi K2.6 (256k ctx, vision)
- `accounts/fireworks/models/qwen3p6-plus` — Qwen3.6 Plus
- `accounts/fireworks/models/minimax-m2p7` — MiniMax M2.7 (196k ctx)

## Architecture

```
frontend/   React 18 + Vite + TypeScript + Tailwind
backend/    FastAPI + SQLAlchemy (SQLite) + httpx
```

The backend proxies all calls to Fireworks, so the API key never reaches
the browser. Streaming uses Server-Sent Events.

## Local development

Requirements: Python 3.11+, Node 20+.

```bash
# 1. Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e .
export FIREWORKS_API_KEY=fw_...
uvicorn app.main:app --reload --port 8000

# 2. Frontend (in another shell)
cd frontend
npm install
npm run dev          # http://localhost:5173, proxies /api to :8000
```

## Production build

```bash
# Build the frontend, copy into backend/static, single-process serve
cd frontend && npm install && npm run build
cp -r dist ../backend/static

cd ../backend
pip install -e .
FIREWORKS_API_KEY=fw_... uvicorn app.main:app --host 0.0.0.0 --port 8000
```

The backend serves `/` from `backend/static/` when present, so a single
FastAPI process handles both the API and the SPA.

## Deployment

Backend is deployed to Fly.io. Set the secret once:

```bash
fly secrets set FIREWORKS_API_KEY=fw_...
fly deploy
```

See [`docs/DOMAIN.md`](docs/DOMAIN.md) for connecting `grebeshok.eu.cc`.

## Environment variables

| Name                | Required | Description                                |
| ------------------- | -------- | ------------------------------------------ |
| `FIREWORKS_API_KEY` | yes      | Fireworks API key                          |
| `DATABASE_URL`      | no       | SQLAlchemy URL. Defaults to local SQLite.  |
| `ALLOWED_ORIGINS`   | no       | CSV of CORS origins. `*` by default.       |
| `DATA_DIR`          | no       | Where SQLite lives. Defaults to `./data`.  |

## Project layout

```
.
├── backend/
│   ├── app/
│   │   ├── main.py        FastAPI app, static files, CORS
│   │   ├── db.py          SQLAlchemy async engine + session
│   │   ├── models.py      Chat, Message ORM models
│   │   ├── schemas.py     Pydantic request/response models
│   │   ├── fireworks.py   Streaming proxy to Fireworks API
│   │   ├── routes.py      /api/* routes
│   │   └── config.py      Settings (env)
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── components/    Sidebar, ChatView, Composer, Message, ...
│   │   ├── hooks/         useChats, useStream
│   │   ├── lib/           api client, markdown, formatters
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   └── styles.css
│   ├── tailwind.config.ts
│   └── package.json
├── docs/
│   └── DOMAIN.md          how to connect grebeshok.eu.cc
├── design-system.md       tokens + visual rules
├── Dockerfile             multi-stage: build front, install back
└── fly.toml               Fly.io app config
```
