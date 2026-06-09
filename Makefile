.PHONY: install test cov lint fmt clean offline-wheel lock

install:
	python -m pip install -e ".[dev]"

test:
	python -m pytest -q

cov:
	python -m pytest -q --cov=sre_kb --cov-fail-under=90

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
