.PHONY: test lint typecheck check
test:
	.venv/bin/pytest -q
lint:
	.venv/bin/ruff check . && .venv/bin/ruff format --check .
typecheck:
	.venv/bin/mypy
check: lint typecheck test
