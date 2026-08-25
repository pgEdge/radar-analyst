#!/bin/bash
#
# End-to-end test: brings up Postgres + radar-analyst via docker compose,
# POSTs a synthetic radar-style zip, polls the job until done, and
# asserts that briefs and a snapshot were persisted.
#
# Uses the mock AI provider (RADAR_ANALYST_AI_PROVIDER=mock) so no real
# API keys are needed.

set -e
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

COMPOSE_FILE="docker-compose.test.yml"
PROJECT="radar-analyst-e2e"

# Host port for the app container. Matches the
# ${RADAR_ANALYST_E2E_PORT:-28080} default in docker-compose.test.yml
# so overriding one overrides the other.
HOST_PORT="${RADAR_ANALYST_E2E_PORT:-28080}"
BASE_URL="http://localhost:${HOST_PORT}"
export RADAR_ANALYST_E2E_PORT="$HOST_PORT"

trap 'docker compose -p "$PROJECT" -f "$COMPOSE_FILE" down -v >/dev/null 2>&1 || true' EXIT

echo -e "${YELLOW}Building + starting stack...${NC}"
docker compose -p "$PROJECT" -f "$COMPOSE_FILE" up -d --build

echo -e "${YELLOW}Waiting for /readyz...${NC}"
for i in $(seq 1 60); do
    if curl -fsS ${BASE_URL}/readyz >/dev/null 2>&1; then
        echo -e "${GREEN}Service ready${NC}"
        break
    fi
    if [ "$i" = "60" ]; then
        echo -e "${RED}Service did not become ready in 60s${NC}"
        docker compose -p "$PROJECT" -f "$COMPOSE_FILE" logs --tail=100 app
        exit 1
    fi
    sleep 1
done

# Generate a radar-format zip so this script has no external
# fixture dependency; the generator is the shared source of
# fixture truth (see src/radar_analyst/tests/make_sample_zip.py).
FIXTURE="$(mktemp /tmp/radar-e2e-XXXXXX.zip)"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHONPATH="$SCRIPT_DIR/src" python3 -m \
    radar_analyst.tests.make_sample_zip "$FIXTURE"

echo -e "${YELLOW}POST /api/uploads...${NC}"
UPLOAD_JSON="$(curl -fsS -F "file=@${FIXTURE}" ${BASE_URL}/api/uploads)"
UPLOAD_ID="$(printf '%s' "$UPLOAD_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["upload_id"])')"
JOB_ID="$(printf '%s' "$UPLOAD_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin)["job_id"])')"
echo "  upload_id=$UPLOAD_ID"
echo "  job_id=$JOB_ID"

echo -e "${YELLOW}Polling job until done (timeout 120s)...${NC}"
for i in $(seq 1 120); do
    STATE="$(curl -fsS "${BASE_URL}/api/jobs/${JOB_ID}" | python3 -c 'import json,sys; print(json.load(sys.stdin)["state"])')"
    if [ "$STATE" = "done" ]; then
        echo -e "${GREEN}Job reached state=done${NC}"
        break
    fi
    if [ "$STATE" = "failed" ]; then
        echo -e "${RED}Job failed${NC}"
        curl -s "${BASE_URL}/api/jobs/${JOB_ID}"
        exit 1
    fi
    if [ "$i" = "120" ]; then
        echo -e "${RED}Timeout waiting for job; last state=$STATE${NC}"
        exit 1
    fi
    sleep 1
done

echo -e "${YELLOW}Verifying SSE stream...${NC}"
# The server runs on plain h11 (no httptools/uvloop), so prove that
# event-stream responses still come back over a real socket. A
# finished job emits one terminal event and closes, so this cannot
# hang.
SSE_BODY="$(mktemp /tmp/radar-e2e-sse-XXXXXX)"
SSE_HEAD="$(curl -fsS --max-time 10 -o "$SSE_BODY" -D - \
    -H 'Accept: text/event-stream' \
    "${BASE_URL}/api/jobs/${JOB_ID}/events")"
if ! printf '%s' "$SSE_HEAD" | grep -qi 'content-type: text/event-stream'; then
    echo -e "${RED}SSE response was not text/event-stream${NC}"
    printf '%s' "$SSE_HEAD"
    exit 1
fi
if ! grep -q '"type": *"done"' "$SSE_BODY"; then
    echo -e "${RED}SSE stream did not carry the terminal event${NC}"
    cat "$SSE_BODY"
    exit 1
fi
rm -f "$SSE_BODY"
echo -e "${GREEN}SSE stream OK${NC}"

echo -e "${YELLOW}Verifying briefs...${NC}"
COUNT="$(curl -fsS "${BASE_URL}/api/uploads/${UPLOAD_ID}/assessment" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["briefs"]))')"
# One brief per category; the five categories are defined in
# analyze/categories.py (Host & OS, PostgreSQL Configuration,
# Workload, Internals & I/O Health, Replication).
if [ "$COUNT" != "5" ]; then
    echo -e "${RED}Expected 5 briefs, got $COUNT${NC}"
    exit 1
fi
echo -e "${GREEN}Got $COUNT briefs${NC}"

echo -e "${YELLOW}Verifying verdicts...${NC}"
# Every brief must carry a valid verdict, and the roll-up must be
# one too: the pipeline's judgement, not just its plumbing.
curl -fsS "${BASE_URL}/api/uploads/${UPLOAD_ID}/assessment" \
    | python3 -c '
import json, sys
body = json.load(sys.stdin)
allowed = {"HEALTHY", "WARNING", "CRITICAL", "UNKNOWN"}
bad = [
    (b["category"], b["verdict"])
    for b in body["briefs"]
    if b["verdict"] not in allowed
]
assert not bad, f"invalid verdicts: {bad}"
assert body["verdict"] in allowed, body["verdict"]
concluded = [
    b for b in body["briefs"] if b["verdict"] != "UNKNOWN"
]
assert concluded, "every category came back UNKNOWN"
print("verdicts:", {b["category"]: b["verdict"] for b in body["briefs"]})
'
echo -e "${GREEN}Verdicts valid${NC}"

echo -e "${YELLOW}Verifying snapshot with coverage canary...${NC}"
SNAP="$(curl -fsS "${BASE_URL}/api/uploads/${UPLOAD_ID}/snapshot")"
UNKNOWN_COUNT="$(printf '%s' "$SNAP" | python3 -c 'import json,sys; print(len(json.load(sys.stdin).get("unknown_entries", [])))')"
if [ "$UNKNOWN_COUNT" != "0" ]; then
    echo -e "${RED}Expected 0 unknown_entries, got $UNKNOWN_COUNT${NC}"
    printf '%s\n' "$SNAP"
    exit 1
fi

echo -e "${GREEN}=== e2e passed ===${NC}"
