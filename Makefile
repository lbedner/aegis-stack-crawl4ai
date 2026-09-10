.PHONY: install test lint fix check

install:
	uv sync --all-extras

test:
	uv run pytest -v

lint:
	uv run ruff check .

fix:
	uv run ruff format .
	uv run ruff check --fix .

check: lint test
