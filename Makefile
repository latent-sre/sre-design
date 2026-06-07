.PHONY: install test lint fmt clean offline-wheel

install:
	python -m pip install -e ".[dev]"

test:
	pytest -q

lint:
	ruff check src tests

fmt:
	ruff format src tests

offline-wheel:
	./scripts/build-offline.sh

clean:
	rm -rf .work .pytest_cache .ruff_cache **/__pycache__
