# web-messenger
Real-time web messenger with private and group chats, message history, WebSocket communication, and basic moderation.

## Stack

- **Backend:** FastAPI, SQLAlchemy 2 (async) + PostgreSQL, Alembic, Redis (pub/sub)
- **Frontend:** React + Vite + TypeScript
- **Infra:** Docker Compose, Caddy (serves the frontend and proxies `/api` to the backend)

## Project layout

```
backend/
  app/
    api/        HTTP and WebSocket routers
    core/       settings, database, redis, security
    models/     SQLAlchemy models
    schemas/    Pydantic request/response models
    services/   business logic shared by REST and WebSocket
    realtime/   event bus (Redis pub/sub → WebSocket connections)
  alembic/      database migrations
  tests/
frontend/
  src/
    api.ts            REST client (access token in memory, refresh via cookie)
    realtime.ts       WebSocket client with auto-reconnect
    messagesState.ts  messages reducer (history, pending messages)
    components/       UI
  Caddyfile           production web server config
docker-compose.yml
```

## Authentication

- `POST /api/auth/register`, `POST /api/auth/login` return a short-lived JWT access token
  (send it as `Authorization: Bearer <token>`) and set a refresh token in an httpOnly cookie
  scoped to `/api/auth`.
- `POST /api/auth/refresh` exchanges the cookie for a new access token. Refresh tokens are
  single-use (rotated on every refresh) and stored only as SHA-256 hashes.
- `POST /api/auth/logout` revokes the refresh token and clears the cookie.

## Chats

- `GET /api/chats` — the user's chats with members; `GET /api/chats/{id}` — one chat
  (404 for non-members).
- `POST /api/chats/direct` — get or create the 1-1 chat with a user (one chat per pair).
- `POST /api/chats/group` — create a group; the creator becomes its admin.
- `PATCH /api/chats/{id}` — rename a group (admin only).
- `POST /api/chats/{id}/members`, `DELETE /api/chats/{id}/members/{user_id}` — add/remove
  members (admin only); any member may remove themselves to leave, except the last admin.

## Messages

- `POST /api/chats/{id}/messages` — send a message. An optional `client_msg_id` (UUID) makes
  retries idempotent: resending returns the stored message instead of a duplicate.
- `GET /api/chats/{id}/messages?before_id=&limit=` — history in chronological order with
  cursor pagination; to load older messages pass `before_id` = id of the oldest loaded one.
- `GET /api/chats/{id}/messages/search?q=` — case-insensitive substring search within a chat,
  newest first (backed by a `pg_trgm` GIN index).
- `GET /api/chats` includes each chat's `last_message` and is ordered by last activity.

## Realtime (WebSocket `/api/ws`)

One connection per browser tab carries events for all of the user's chats.

1. The client sends `{"type": "auth", "token": "<access token>"}`; the server answers `auth.ok`
   or closes the socket with code `4401`.
2. `{"type": "message.send", "chat_id", "text", "client_msg_id"}` stores the message and
   answers `message.ack` (status "delivered to the server"); all chat members then get
   `message.new`. Errors come back as `error` events carrying the `client_msg_id`.
3. Chat changes (created, renamed, members added/removed) are announced as `chat.updated`.

Events are fanned out through Redis pub/sub, so several backend processes can serve
WebSockets at once. The frontend keeps unconfirmed messages and resends them after a
reconnect; `client_msg_id` makes that safe from duplicates.

## Running with Docker

```bash
cp .env.example .env   # then set JWT_SECRET
docker compose up -d --build
```

- App: http://localhost:8080
- API docs: http://127.0.0.1:8000/docs

## Local development

Requires [uv](https://docs.astral.sh/uv/) and Docker.

```bash
docker compose up -d postgres redis   # infrastructure only
cd backend
cp .env.example .env   # then set JWT_SECRET
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

Frontend (Node 24+), in another terminal; Vite proxies `/api` (and the WebSocket) to
`http://127.0.0.1:8000`, override with `BACKEND_URL`:

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

### Tests and linting

Tests expect Postgres and Redis from `docker compose` to be running. They use a separate
`messenger_test` database that is recreated and migrated on every run.

```bash
cd backend
uv run pytest
uv run ruff check . && uv run ruff format --check .

cd ../frontend
npm run build      # type-check + production build
npm run lint && npm run format:check
```

### Migrations

```bash
cd backend
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```
