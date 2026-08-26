# Thin wrapper over the scripts that already do the work, so the
# usual verbs exist. run-ci-local.sh remains the gate: it is what CI
# runs and what has to exit 0 before a commit.

PY      := .venv/bin/python
PIP     := .venv/bin/pip
PYTEST  := .venv/bin/pytest
VENV    := .venv

.PHONY: help venv build test unit e2e lint typecheck ci docs notice clean

help:
	@echo "make venv       create .venv and install dev dependencies"
	@echo "make build      build the Astro console and the wheel"
	@echo "make test       unit and integration tests"
	@echo "make e2e        end-to-end suite against the compose stack"
	@echo "make lint       flake8 and ruff"
	@echo "make typecheck  mypy and pyright, both strict"
	@echo "make ci         everything, the way CI runs it"
	@echo "make docs       build the documentation site"
	@echo "make notice     regenerate NOTICE.txt from the dependencies"
	@echo "make clean      remove build output and caches"

$(VENV):
	python3 -m venv $(VENV)
	$(PIP) install --upgrade pip build
	$(PIP) install -e '.[dev]'

venv: $(VENV)

build: $(VENV)
	cd web && npm ci && npm run build
	$(PY) -m build --wheel

test: $(VENV)
	$(PYTEST) -v -m 'not e2e' --cov --cov-fail-under=85

unit: $(VENV)
	$(PYTEST) -q -m 'not e2e'

e2e:
	./test-radar-analyst.sh

lint: $(VENV)
	cd src/radar_analyst && ../../$(VENV)/bin/python -m flake8 . \
		--count --ignore F722,W503 --max-line-length=79 \
		--max-complexity=8 --statistics
	$(VENV)/bin/ruff check src/radar_analyst
	$(VENV)/bin/interrogate

typecheck: $(VENV)
	$(VENV)/bin/mypy src/radar_analyst
	$(VENV)/bin/pyright

ci:
	./run-ci-local.sh

docs: $(VENV)
	$(PIP) install -q mkdocs-material
	$(VENV)/bin/mkdocs build --strict

# NOTICE.txt lists the licences of everything the wheel pulls in.
# The container image and any future deb or rpm vendor the whole
# dependency tree, so the list has to travel with them.
notice: $(VENV)
	$(PIP) install -q pip-licenses
	$(VENV)/bin/pip-licenses --format=plain-vertical \
		--with-license-file --no-license-path \
		--output-file=NOTICE.txt
	@echo "wrote NOTICE.txt"

clean:
	rm -rf dist build .pytest_cache .mypy_cache .ruff_cache \
		.coverage htmlcov site src/radar_analyst/webdist \
		web/dist web/.astro
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
