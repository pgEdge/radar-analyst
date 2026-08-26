#!/bin/bash
#
# End-to-end test of the bundled image: the one-command deployment an
# end user gets. Runs the image on its own, with no database service
# and no configuration, uploads a radar-format zip, and then restarts
# the container to prove the archive and its assessment survived.
#
# Uses the mock AI provider (RADAR_ANALYST_AI_PROVIDER=mock) so no
# real API keys are needed.

set -e
set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

IMAGE="${RADAR_ANALYST_IMAGE:-radar-analyst-local-test}"
CONTAINER="radar-analyst-bundle-test"
VOLUME="radar-analyst-bundle-test-data"
HOST_PORT="${RADAR_ANALYST_IMAGE_TEST_PORT:-28081}"
BASE_URL="http://127.0.0.1:${HOST_PORT}"

cleanup() {
    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
    docker volume rm "$VOLUME" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

wait_ready() {
    local label="$1"
    for i in $(seq 1 90); do
        if curl -fsS "${BASE_URL}/readyz" >/dev/null 2>&1; then
            echo -e "${GREEN}${label}: ready${NC}"
            return 0
        fi
        if [ "$(docker inspect -f '{{.State.Running}}' \
                "$CONTAINER" 2>/dev/null)" != "true" ]; then
            echo -e "${RED}${label}: container exited${NC}"
            docker logs "$CONTAINER" 2>&1 | tail -40
            exit 1
        fi
        sleep 1
    done
    echo -e "${RED}${label}: not ready in 90s${NC}"
    docker logs "$CONTAINER" 2>&1 | tail -40
    exit 1
}

# This is the command the documentation gives an end user, with the
# mock provider added so the test needs no API key.
echo -e "${YELLOW}Starting the bundled image...${NC}"
docker run -d --name "$CONTAINER" \
    -p "127.0.0.1:${HOST_PORT}:8080" \
    -v "${VOLUME}:/data" \
    -e RADAR_ANALYST_AI_PROVIDER=mock \
    -e RADAR_ANALYST_TEST=1 \
    "$IMAGE" >/dev/null

wait_ready "First start"

echo -e "${YELLOW}Checking the bundled server is not on the network...${NC}"
# The analyst publishes a port on purpose; the database behind it
# must not have one, or a single -p typo would expose it.
PORTS="$(docker port "$CONTAINER")"
if printf '%s' "$PORTS" | grep -q '5432'; then
    echo -e "${RED}PostgreSQL is published: ${PORTS}${NC}"
    exit 1
fi
if docker exec "$CONTAINER" \
        python -c "import socket,sys; s=socket.socket();
sys.exit(0 if s.connect_ex(('127.0.0.1', 5432)) != 0 else 1)"; then
    echo -e "${GREEN}No TCP listener on 5432${NC}"
else
    echo -e "${RED}PostgreSQL accepted a TCP connection${NC}"
    exit 1
fi

echo -e "${YELLOW}Checking the service does not run as root...${NC}"
# PID 1 is the analyst itself: the entrypoint execs setpriv, which
# execs the service, so the whole tree (PostgreSQL included) runs
# unprivileged. Read the process rather than asking `docker exec`,
# which gets its own session as the image's default user.
docker exec "$CONTAINER" python -c "
import pathlib, sys
status = pathlib.Path('/proc/1/status').read_text().splitlines()
line = next(x for x in status if x.startswith('Uid:'))
uids = set(line.split()[1:])
print('  PID 1 uids:', ' '.join(sorted(uids)))
assert uids == {'10001'}, f'service is not unprivileged: {line}'
"

FIXTURE="$(mktemp /tmp/radar-bundle-XXXXXX.zip)"
trap 'rm -f "$FIXTURE"; cleanup' EXIT
PYTHONPATH="$SCRIPT_DIR/src" python3 -m \
    radar_analyst.tests.make_sample_zip "$FIXTURE"

echo -e "${YELLOW}POST /api/uploads...${NC}"
UPLOAD_JSON="$(curl -fsS -F "file=@${FIXTURE}" ${BASE_URL}/api/uploads)"
UPLOAD_ID="$(printf '%s' "$UPLOAD_JSON" | python3 -c \
    'import json,sys; print(json.load(sys.stdin)["upload_id"])')"
JOB_ID="$(printf '%s' "$UPLOAD_JSON" | python3 -c \
    'import json,sys; print(json.load(sys.stdin)["job_id"])')"
echo "  upload_id=$UPLOAD_ID"

echo -e "${YELLOW}Polling job until done (timeout 120s)...${NC}"
for i in $(seq 1 120); do
    STATE="$(curl -fsS "${BASE_URL}/api/jobs/${JOB_ID}" | python3 -c \
        'import json,sys; print(json.load(sys.stdin)["state"])')"
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

echo -e "${YELLOW}Checking the archive landed in the volume...${NC}"
docker exec "$CONTAINER" \
    python -c "
import pathlib, sys
archives = sorted(pathlib.Path('/data/archives').rglob('*'))
files = [p for p in archives if p.is_file()]
assert files, 'no archive was written under /data/archives'
assert pathlib.Path('/data/db/PG_VERSION').is_file(), 'no PGDATA'
print('  archives:', ' '.join(str(p) for p in files))
"

# The point of the volume: stop the container, start a new one, and
# find the work still there. This is what separates a persistent
# deployment from one that quietly loses everything on upgrade.
echo -e "${YELLOW}Restarting the container...${NC}"
docker restart "$CONTAINER" >/dev/null
wait_ready "Second start"

echo -e "${YELLOW}Verifying the assessment survived the restart...${NC}"
curl -fsS "${BASE_URL}/api/uploads/${UPLOAD_ID}/assessment" \
    | python3 -c '
import json, sys
body = json.load(sys.stdin)
allowed = {"HEALTHY", "WARNING", "CRITICAL", "UNKNOWN"}
assert len(body["briefs"]) == 5, body["briefs"]
assert body["verdict"] in allowed, body["verdict"]
concluded = [b for b in body["briefs"] if b["verdict"] != "UNKNOWN"]
assert concluded, "every category came back UNKNOWN"
print("  verdicts:", {b["category"]: b["verdict"] for b in body["briefs"]})
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
# Out of the box there is no shared secret to configure, but deletes
# still have to be authenticated.
UNAUTH="$(curl -s -o /dev/null -w '%{http_code}' -X DELETE \
    "${BASE_URL}/api/uploads/${UPLOAD_ID}")"
if [ "$UNAUTH" != "401" ]; then
    echo -e "${RED}Unauthenticated delete returned ${UNAUTH}, want 401${NC}"
    exit 1
fi
TOKEN="$(docker exec "$CONTAINER" cat /data/admin-token)"
CODE="$(curl -s -o /dev/null -w '%{http_code}' -X DELETE \
    -H "Authorization: Bearer ${TOKEN}" \
    "${BASE_URL}/api/uploads/${UPLOAD_ID}")"
if [ "$CODE" != "204" ]; then
    echo -e "${RED}Delete returned ${CODE}, want 204${NC}"
    exit 1
fi
echo -e "${GREEN}Delete authorised and applied${NC}"

echo -e "${GREEN}=== bundled-image e2e passed ===${NC}"
