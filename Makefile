.PHONY: install test cov lint fmt atlas atlas-check clean offline-wheel lock schema-ref

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

atlas:
	python -m sre_kb.cli atlas --target .

atlas-check:
	python -m sre_kb.cli atlas-check --target .

lock:
	python -m pip install -q pip-tools
	pip-compile --generate-hashes --output-file=requirements.lock pyproject.toml

schema-ref:
	python tools/gen_schema_ref.py

offline-wheel:
	./scripts/build-offline.sh

clean:
	rm -rf .work .pytest_cache .ruff_cache .hypothesis .coverage **/__pycache__
