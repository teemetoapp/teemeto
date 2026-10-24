.PHONY: dev down test lint typecheck migrate clean

# Run local development containers (PostgreSQL + pgvector, Redis)
dev:
	docker compose -f infra/docker-compose.yml up -d

# Stop and tear down containers
down:
	docker compose -f infra/docker-compose.yml down

# Run backend test suite (pytest)
test:
	pytest tests/ -v

# Run linters (ruff)
lint:
	ruff check .

# Run strict type checking (mypy)
typecheck:
	mypy --strict packages/ services/

# Apply database migrations
migrate:
	alembic upgrade head

# Clean cache directories
clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .mypy_cache
