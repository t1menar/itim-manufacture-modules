.PHONY: venv test lint typecheck check status
venv:
	~/.local/bin/python3.12 -m venv .venv
	.venv/bin/pip -q install -e ~/projects/manufacture-sdk-python -e ../../packages/mf-storage pytest pytest-asyncio ruff mypy
	.venv/bin/pip -q install -e . --no-deps
test:
	.venv/bin/pytest -q
lint:
	.venv/bin/ruff check . && .venv/bin/ruff format --check .
typecheck:
	.venv/bin/mypy
check: lint typecheck test
status:
	.venv/bin/mstudio status
