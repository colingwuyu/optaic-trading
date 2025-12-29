
.PHONY: lint test build build-webui dist dev dev-deps dev-api up down start restart rebuild fresh migrate upgrade downgrade db-shell db-upgrade logs ps

lint:
	uv run ruff check .

test:
	uv run pytest

build: build-webui dist

build-webui:
	uv run python scripts/build_webui.py

dist:
	uv build

dev: dev-deps
	uv run python scripts/dev.py

dev-deps:
	docker compose -f infra/docker-compose.yml up -d postgres redis minio minio-init centrifugo

dev-api:
	uv run uvicorn apps.api.main:app --reload --host 127.0.0.1 --port 8081 --reload-dir apps/api --reload-dir libs

up:
	docker compose -f infra/docker-compose.yml up --build -d postgres redis centrifugo api worker web

start: up

restart:
	docker compose -f infra/docker-compose.yml restart

rebuild:
	docker compose -f infra/docker-compose.yml up -d --build
	$(MAKE) db-upgrade

fresh:
	docker compose -f infra/docker-compose.yml down -v --remove-orphans
	docker compose -f infra/docker-compose.yml up -d --build

down:
	docker compose -f infra/docker-compose.yml down

migrate:
	uv run alembic -c libs/db/alembic.ini revision --autogenerate -m "$(desc)"

upgrade:
	uv run alembic -c libs/db/alembic.ini upgrade head

downgrade:
	uv run alembic -c libs/db/alembic.ini downgrade -1

db-shell:
	docker compose -f infra/docker-compose.yml exec postgres psql -U postgres

db-upgrade:
	docker compose -f infra/docker-compose.yml exec -T api uv run alembic -c libs/db/alembic.ini upgrade head

logs:
	docker compose -f infra/docker-compose.yml logs -f --tail=200

ps:
	docker compose -f infra/docker-compose.yml ps
