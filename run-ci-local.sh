#!/bin/bash
#
# Full local CI: two linters and two type checkers on the
# Python side, eslint + prettier + vitest on the web side, npm ci + Astro
# build, Python wheel build, Docker build, and the end-to-end
# suite against the docker-compose stack.
# Structure mirrors radar/run-ci-local.sh.
#
# Any failure aborts. Timestamped log file is emitted alongside.

set -e
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOGFILE="ci-$(date +%Y%m%d-%H%M%S).log"

# Which PostgreSQL the database-backed tests run against.
# CI iterates 16, 17, and 18; a local run uses one.
export RADAR_ANALYST_PG_MAJOR="${RADAR_ANALYST_PG_MAJOR:-18}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "$@" | tee -a "$LOGFILE"; }

log "=== radar-analyst Local CI ==="
log "Log file: $LOGFILE"
log "PostgreSQL: ${RADAR_ANALYST_PG_MAJOR} (pgEdge minimal)"
log ""

# Resolve Python tools: prefer venv in repo root if present.
# Use absolute paths so subshells (cd src/radar_analyst && ...) can
# still find the tools after changing directory.
if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
    PY="$SCRIPT_DIR/.venv/bin/python"
    PIP="$SCRIPT_DIR/.venv/bin/pip"
    PYTEST="$SCRIPT_DIR/.venv/bin/pytest"
    MYPY="$SCRIPT_DIR/.venv/bin/mypy"
    RUFF="$SCRIPT_DIR/.venv/bin/ruff"
    PYRIGHT="$SCRIPT_DIR/.venv/bin/pyright"
    FLAKE8="$SCRIPT_DIR/.venv/bin/python -m flake8"
else
    PY="python3"
    PIP="pip"
    PYTEST="pytest"
    MYPY="mypy"
    RUFF="ruff"
    PYRIGHT="pyright"
    FLAKE8="python3 -m flake8"
fi

log "${YELLOW}Step 1/11: flake8${NC}"
# Same invocation as src/radar_analyst/flake.sh.
(cd src/radar_analyst && eval "$FLAKE8" . --count --ignore F722,W503 --max-line-length=79 --max-complexity=8 --statistics) 2>&1 | tee -a "$LOGFILE"
log "${GREEN}  flake8 passed${NC}"
log ""

log "${YELLOW}Step 2/11: ruff${NC}"
# Runs alongside flake8 for the rules flake8 has no equivalent for.
# Lint only: the project has no auto-formatter.
eval "$RUFF check src/radar_analyst" 2>&1 | tee -a "$LOGFILE"
eval "$SCRIPT_DIR/.venv/bin/interrogate" 2>&1 | tee -a "$LOGFILE"
log "${GREEN}  ruff passed${NC}"
log ""

log "${YELLOW}Step 3/11: mypy${NC}"
eval "$MYPY src/radar_analyst" 2>&1 | tee -a "$LOGFILE"
log "${GREEN}  mypy passed${NC}"
log ""

log "${YELLOW}Step 4/11: pyright${NC}"
eval "$PYRIGHT" 2>&1 | tee -a "$LOGFILE"
log "${GREEN}  pyright passed${NC}"
log ""

log "${YELLOW}Step 5/11: pytest (unit + radar-format suite)${NC}"
# The format-validation tests run against a generated
# radar-format archive; point RADAR_SAMPLE_ZIP at a real one to
# validate against live radar output instead.
if [ -z "${RADAR_SAMPLE_ZIP:-}" ]; then
    RADAR_SAMPLE_ZIP="$(mktemp /tmp/radar-sample-XXXXXX.zip)"
    (
        export PYTHONPATH="$SCRIPT_DIR/src"
        eval "$PY -m radar_analyst.tests.make_sample_zip \
            '$RADAR_SAMPLE_ZIP'"
    ) 2>&1 | tee -a "$LOGFILE"
    trap 'rm -f "$RADAR_SAMPLE_ZIP"' EXIT
fi
export RADAR_SAMPLE_ZIP
eval "$PYTEST -v -m 'not e2e' --cov --cov-report=term" 2>&1 | tee -a "$LOGFILE"
log "${GREEN}  unit tests passed${NC}"
log ""

log "${YELLOW}Step 6/11: npm ci (web/)${NC}"
(cd web && npm ci) 2>&1 | tee -a "$LOGFILE"
log "${GREEN}  npm ci passed${NC}"
log ""

log "${YELLOW}Step 7/11: web lint + unit tests${NC}"
(cd web && npx eslint . && npx prettier --check . && npm test) 2>&1 | tee -a "$LOGFILE"
log "${GREEN}  web checks passed${NC}"
log ""

log "${YELLOW}Step 8/11: Astro build${NC}"
(cd web && npm run build) 2>&1 | tee -a "$LOGFILE"
log "${GREEN}  Astro build passed${NC}"
log ""

log "${YELLOW}Step 9/11: python wheel build${NC}"
eval "$PY -m build --wheel" 2>&1 | tee -a "$LOGFILE"
log "${GREEN}  wheel built${NC}"
log ""

log "${YELLOW}Step 10/11: Docker image build${NC}"
docker build -t radar-analyst-local-test . 2>&1 | tee -a "$LOGFILE"
log "${GREEN}  docker image built${NC}"
log ""

log "${YELLOW}Step 11/11: e2e inside Docker (test-radar-analyst.sh)${NC}"
./test-radar-analyst.sh 2>&1 | tee -a "$LOGFILE"
log "${GREEN}  e2e passed${NC}"
log ""

log "${YELLOW}Cleanup${NC}"
docker rmi radar-analyst-local-test >/dev/null 2>&1 || true

log ""
log "${GREEN}=== All CI steps passed ===${NC}"
