#!/bin/bash
#
# Full local CI: lint, type check, unit tests, npm ci + Astro
# build, Python wheel build, Docker build, and both e2e suites
# inside Docker (the service deployment and the bundled image).
# Structure mirrors radar/run-ci-local.sh.
#
# Any failure aborts. Timestamped log file is emitted alongside.

set -e
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

LOGFILE="ci-$(date +%Y%m%d-%H%M%S).log"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log() { echo -e "$@" | tee -a "$LOGFILE"; }

log "=== radar-analyst Local CI ==="
log "Log file: $LOGFILE"
log ""

# Resolve Python tools: prefer venv in repo root if present.
# Use absolute paths so subshells (cd src/radar_analyst && ...) can
# still find the tools after changing directory.
if [ -x "$SCRIPT_DIR/.venv/bin/python" ]; then
    PY="$SCRIPT_DIR/.venv/bin/python"
    PIP="$SCRIPT_DIR/.venv/bin/pip"
    PYTEST="$SCRIPT_DIR/.venv/bin/pytest"
    MYPY="$SCRIPT_DIR/.venv/bin/mypy"
    FLAKE8="$SCRIPT_DIR/.venv/bin/python -m flake8"
else
    PY="python3"
    PIP="pip"
    PYTEST="pytest"
    MYPY="mypy"
    FLAKE8="python3 -m flake8"
fi

log "${YELLOW}Step 1/9: flake8${NC}"
# Same invocation as src/radar_analyst/flake.sh.
(cd src/radar_analyst && eval "$FLAKE8" . --count --ignore F722,W503 --max-line-length=79 --max-complexity=8 --statistics) 2>&1 | tee -a "$LOGFILE"
log "${GREEN}  flake8 passed${NC}"
log ""

log "${YELLOW}Step 2/9: mypy${NC}"
eval "$MYPY src/radar_analyst" 2>&1 | tee -a "$LOGFILE"
log "${GREEN}  mypy passed${NC}"
log ""

log "${YELLOW}Step 3/9: pytest (unit + radar-format suite)${NC}"
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
eval "$PYTEST -v -m 'not e2e'" 2>&1 | tee -a "$LOGFILE"
log "${GREEN}  unit tests passed${NC}"
log ""

log "${YELLOW}Step 4/9: npm ci (web/)${NC}"
(cd web && npm ci) 2>&1 | tee -a "$LOGFILE"
log "${GREEN}  npm ci passed${NC}"
log ""

log "${YELLOW}Step 5/9: Astro build${NC}"
(cd web && npm run build) 2>&1 | tee -a "$LOGFILE"
log "${GREEN}  Astro build passed${NC}"
log ""

log "${YELLOW}Step 6/9: python wheel build${NC}"
eval "$PY -m build --wheel" 2>&1 | tee -a "$LOGFILE"
log "${GREEN}  wheel built${NC}"
log ""

log "${YELLOW}Step 7/9: Docker image build${NC}"
docker build -t radar-analyst-local-test . 2>&1 | tee -a "$LOGFILE"
log "${GREEN}  docker image built${NC}"
log ""

log "${YELLOW}Step 8/9: e2e inside Docker (test-radar-analyst.sh)${NC}"
./test-radar-analyst.sh 2>&1 | tee -a "$LOGFILE"
log "${GREEN}  e2e passed${NC}"
log ""

log "${YELLOW}Step 9/9: bundled-image e2e (test-bundled-image.sh)${NC}"
./test-bundled-image.sh 2>&1 | tee -a "$LOGFILE"
log "${GREEN}  bundled-image e2e passed${NC}"
log ""

log "${YELLOW}Cleanup${NC}"
docker rmi radar-analyst-local-test >/dev/null 2>&1 || true

log ""
log "${GREEN}=== All CI steps passed ===${NC}"
