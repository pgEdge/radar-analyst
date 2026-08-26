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

COMPOSE=(docker compose -p "$PROJECT" -f "$COMPOSE_FILE")

echo -e "${YELLOW}Verifying only the analyst can reach the database...${NC}"
# A container's bridge address is routable from the host, so "no
# published port" is not containment on its own. The database must
# refuse a direct connection from here and from any other container.
DB_IP="$(docker inspect -f \
    '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' \
    "$("${COMPOSE[@]}" ps -q db)")"
python3 - "$DB_IP" <<'PYEOF'
import socket
import sys

ip = sys.argv[1]
sock = socket.socket()
sock.settimeout(5)
rc = sock.connect_ex((ip, 5432))
if rc == 0:
    sys.exit(f"the database at {ip}:5432 accepted a connection "
             "from the host")
print(f"  {ip}:5432 refused the host (errno {rc})")
PYEOF

echo -e "${YELLOW}Verifying the analyst does not run as root...${NC}"
# PID 1 is the analyst: the entrypoint execs setpriv, which execs
# the service, so nothing is served with privileges.
"${COMPOSE[@]}" exec -T app python -c "
import pathlib
status = pathlib.Path('/proc/1/status').read_text().splitlines()
line = next(x for x in status if x.startswith('Uid:'))
uids = set(line.split()[1:])
print('  PID 1 uids:', ' '.join(sorted(uids)))
assert uids == {'10001'}, f'service is not unprivileged: {line}'
"

echo -e "${YELLOW}Verifying the archive landed in the volume...${NC}"
"${COMPOSE[@]}" exec -T app python -c "
import pathlib
files = [p for p in pathlib.Path('/data/archives').rglob('*') if p.is_file()]
assert files, 'no archive was written under /data/archives'
print('  archives:', ' '.join(str(p) for p in files))
"

# The point of the volumes: stop the stack, bring it back, and find
# the work still there. This is what separates a deployment someone
# can rely on from one that quietly loses everything on upgrade.
echo -e "${YELLOW}Restarting the stack...${NC}"
"${COMPOSE[@]}" stop >/dev/null
"${COMPOSE[@]}" start >/dev/null
for i in $(seq 1 90); do
    curl -fsS ${BASE_URL}/readyz >/dev/null 2>&1 && break
    if [ "$i" = "90" ]; then
        echo -e "${RED}Service did not come back in 90s${NC}"
        "${COMPOSE[@]}" logs --tail=50 app
        exit 1
    fi
    sleep 1
done
echo -e "${GREEN}Stack came back${NC}"

echo -e "${YELLOW}Verifying the assessment survived the restart...${NC}"
curl -fsS "${BASE_URL}/api/uploads/${UPLOAD_ID}/assessment" \
    | python3 -c '
import json, sys
body = json.load(sys.stdin)
assert len(body["briefs"]) == 5, body["briefs"]
print("  verdict still:", body["verdict"])
'

echo -e "${YELLOW}Verifying the stored archive is still readable...${NC}"
# Streaming an entry back out proves the zip itself survived, not
# just the rows describing it.
ENTRY="$(curl -fsS "${BASE_URL}/api/uploads/${UPLOAD_ID}/files" \
    | python3 -c \
    'import json,sys; print(json.load(sys.stdin)["items"][0]["path"])')"
curl -fsS -o /dev/null \
    "${BASE_URL}/api/uploads/${UPLOAD_ID}/files/${ENTRY}"
echo -e "${GREEN}Read back ${ENTRY}${NC}"

echo -e "${YELLOW}Verifying delete works with the generated token...${NC}"
# Nobody configured a shared secret, but deletes still have to be
# authenticated.
UNAUTH="$(curl -s -o /dev/null -w '%{http_code}' -X DELETE \
    "${BASE_URL}/api/uploads/${UPLOAD_ID}")"
if [ "$UNAUTH" != "401" ]; then
    echo -e "${RED}Unauthenticated delete returned ${UNAUTH}, want 401${NC}"
    exit 1
fi
TOKEN="$("${COMPOSE[@]}" exec -T app cat /data/admin-token | tr -d '\r\n')"
CODE="$(curl -s -o /dev/null -w '%{http_code}' -X DELETE \
    -H "Authorization: Bearer ${TOKEN}" \
    "${BASE_URL}/api/uploads/${UPLOAD_ID}")"
if [ "$CODE" != "204" ]; then
    echo -e "${RED}Delete returned ${CODE}, want 204${NC}"
    exit 1
fi
echo -e "${GREEN}Delete authorised and applied${NC}"

echo -e "${GREEN}=== e2e passed ===${NC}"
