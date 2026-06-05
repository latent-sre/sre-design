.PHONY: install test lint fmt clean

install:
	python -m pip install -e ".[dev]"

test:
	pytest -q

lint:
	ruff check src tests

fmt:
	ruff format src tests

clean:
	rm -rf .work .pytest_cache .ruff_cache **/__pycache__
