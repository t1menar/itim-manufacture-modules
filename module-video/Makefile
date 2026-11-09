.PHONY: sync test lint typecheck imports check
sync:
	uv sync
test:
	uv run pytest
lint:
	uv run ruff check . && uv run ruff format --check .
typecheck:
	uv run mypy
imports:
	uv run lint-imports
check: lint typecheck imports test
