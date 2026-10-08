.PHONY: test lint format

test:
	python -m pytest

lint:
	ruff check .

format:
	ruff format .
