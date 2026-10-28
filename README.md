# web-messenger
Real-time web messenger with private and group chats, message history, WebSocket communication, and basic moderation.

## Stack

- **Backend:** FastAPI, SQLAlchemy 2 (async) + PostgreSQL, Alembic, Redis
- **Frontend:** React + Vite (coming later)
- **Infra:** Docker Compose

## Project layout

```
backend/
  app/
    api/        HTTP routers
    core/       settings, database, redis
    models/     SQLAlchemy models
  alembic/      database migrations
  tests/
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

## Running with Docker

```bash
cp .env.example .env   # then set JWT_SECRET
docker compose up -d --build
curl http://127.0.0.1:8000/health/ready
```

API docs: http://127.0.0.1:8000/docs

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

### Tests and linting

Tests expect Postgres and Redis from `docker compose` to be running. They use a separate
`messenger_test` database that is recreated and migrated on every run.

```bash
cd backend
uv run pytest
uv run ruff check . && uv run ruff format --check .
```

### Migrations

```bash
cd backend
uv run alembic revision --autogenerate -m "describe change"
uv run alembic upgrade head
```
