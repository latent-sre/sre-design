.PHONY: install test lint fmt clean offline-wheel lock

install:
	python -m pip install -e ".[dev]"

test:
	pytest -q

lint:
	ruff check src tests

fmt:
	ruff format src tests

lock:
	python -m pip install -q pip-tools
	pip-compile --generate-hashes --output-file=requirements.lock pyproject.toml

offline-wheel:
	./scripts/build-offline.sh

clean:
	rm -rf .work .pytest_cache .ruff_cache **/__pycache__
