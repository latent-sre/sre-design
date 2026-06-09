.PHONY: install test lint fmt clean offline-wheel lock

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest -q

lint:
	python -m ruff check src tests

fmt:
	python -m ruff format src tests

lock:
	python -m pip install -q pip-tools
	pip-compile --generate-hashes --output-file=requirements.lock pyproject.toml

offline-wheel:
	./scripts/build-offline.sh

clean:
	rm -rf .work .pytest_cache .ruff_cache **/__pycache__
