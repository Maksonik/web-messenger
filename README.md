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

## Running with Docker

```bash
docker compose up -d --build
curl http://127.0.0.1:8000/health/ready
```

API docs: http://127.0.0.1:8000/docs

## Local development

Requires [uv](https://docs.astral.sh/uv/) and Docker.

```bash
docker compose up -d postgres redis   # infrastructure only
cd backend
cp .env.example .env
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

### Tests and linting

Tests expect Postgres and Redis from `docker compose` to be running.

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
