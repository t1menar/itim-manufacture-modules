.PHONY: sync test lint typecheck check
sync:
	uv sync
test:
	uv run pytest
lint:
	uv run ruff check . && uv run ruff format --check .
typecheck:
	uv run mypy
check: lint test
check-strict: lint typecheck test
