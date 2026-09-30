#!/usr/bin/env bash
#
# Regenerates the console screenshots in docs/img/ that the README and
# the documentation show: the front page, and one assessment with one
# category open on its brief, each in the light and the dark theme.
# capture-screenshots.mjs takes the pictures, as JPEG files.
#
#   ./capture-screenshots.sh        (or: make screenshots)
#
# Every archive is a real radar collection. The showcase, the assessment
# the pictures open, is an anonymized collection of a real server, kept
# outside git in data/showcase/ (SHOWCASE_ARCHIVE names another). The
# two other hosts in the list are collected on the spot: for each, a
# throwaway pgEdge PostgreSQL container under a fictional hostname gets
# a database and a pgbench workload, and the latest radar release runs
# inside it as root, so the system facts are the container's and
# nothing about this machine beyond its kernel, processors and memory
# is collected.
#
# The analyst is built from this checkout and runs as a compose project
# of its own, so an analyst you already run keeps its data, although
# the console port, 8080, has to be free. The showcase host's briefs
# are written by the provider configured in .env, so the pictures show
# real output; the other two hosts are assessed without a provider, so
# a run costs one assessment's worth of provider calls.
#
# Needs Docker with the Compose plugin, curl, Node 22 or later,
# Chromium or Chrome (CHROME names the binary), and a provider
# credential in .env.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

export COMPOSE_PROJECT_NAME=radar-analyst-screenshots
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.build.yml)
BASE=http://localhost:8080
OUT="$ROOT/docs/img"
PG_IMAGE=ghcr.io/pgedge/pgedge-postgres:18-spock5-minimal
SHOWCASE="${SHOWCASE_ARCHIVE:-$(ls "$ROOT"/data/showcase/radar-*.zip 2>/dev/null | head -1)}"
SHOWCASE_CATEGORY="PostgreSQL Configuration"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY=python3

die() { echo "capture-screenshots: $*" >&2; exit 1; }
say() { echo "capture-screenshots: $*"; }

WORK="$(mktemp -d)"
HOSTS=()
cleanup() {
    for host in "${HOSTS[@]}"; do
        docker rm -f "shot-$host" >/dev/null 2>&1 || true
    done
    "${COMPOSE[@]}" down -v >/dev/null 2>&1 || true
    rm -rf "$WORK"
}
trap cleanup EXIT

command -v docker >/dev/null 2>&1 || die "docker is not installed"
node -e 'process.exit(typeof WebSocket === "function" ? 0 : 1)' \
    2>/dev/null || die "Node 22 or later is needed"
if curl -s -o /dev/null "$BASE/"; then
    die "something already answers on $BASE; stop it first"
fi
[ -f "$SHOWCASE" ] || die "no showcase archive: put an anonymized radar \
collection in data/showcase/, or name one with SHOWCASE_ARCHIVE"

case "$(uname -m)" in
    x86_64) ARCH=amd64 ;;
    aarch64 | arm64) ARCH=arm64 ;;
    *) die "radar is not released for $(uname -m)" ;;
esac
say "downloading the latest radar release"
curl -fsSL -o "$WORK/radar" \
    "https://github.com/pgEdge/radar/releases/latest/download/radar-linux-$ARCH"
chmod +x "$WORK/radar"

# sql HOST DB: runs standard input in database DB on HOST's server.
sql() {
    docker exec -i -e PGPASSWORD=postgres "shot-$1" \
        psql -X -q -v ON_ERROR_STOP=1 -h 127.0.0.1 -U postgres -d "$2" \
        >/dev/null
}

# start_host HOST [postgres -c settings...]: a fresh server. The
# image's initdb would otherwise trust TCP connections on loopback,
# which the analyst rightly reports as critical.
start_host() {
    local host="$1"
    shift
    HOSTS+=("$host")
    docker run -d --name "shot-$host" --hostname "$host" \
        -e POSTGRES_PASSWORD=postgres \
        -e POSTGRES_HOST_AUTH_METHOD=scram-sha-256 \
        -e POSTGRES_INITDB_ARGS="--encoding=UTF8 --locale=C.UTF-8 --auth-host=scram-sha-256" \
        "$PG_IMAGE" postgres -c logging_collector=off "$@" >/dev/null
    for _ in $(seq 1 60); do
        docker exec "shot-$host" pg_isready -q -h 127.0.0.1 && return 0
        sleep 1
    done
    die "the server for $host did not start"
}

# workload HOST DB SCALE SECONDS: pgbench tables and traffic in DB.
workload() {
    docker exec -e PGPASSWORD=postgres "shot-$1" \
        pgbench -q -i -s "$3" -h 127.0.0.1 -U postgres "$2" >/dev/null 2>&1
    docker exec -e PGPASSWORD=postgres "shot-$1" \
        pgbench -c 4 -T "$4" -h 127.0.0.1 -U postgres "$2" >/dev/null 2>&1
}

# collect HOST: runs radar in HOST's container and copies the archive
# into the work directory.
collect() {
    local host="$1" archive
    docker cp "$WORK/radar" "shot-$host:/tmp/radar" >/dev/null
    docker exec -u 0 -w /tmp -e PGPASSWORD=postgres "shot-$host" \
        /tmp/radar -h 127.0.0.1 -U postgres -d postgres >/dev/null 2>&1 \
        || die "radar failed on $host"
    archive="$(docker exec "shot-$host" sh -c 'ls /tmp/radar-*.zip')"
    docker cp "shot-$host:$archive" "$WORK/" >/dev/null
    docker rm -f "shot-$host" >/dev/null
}

say "collecting db02.example.com: tuned, one busy database"
start_host db02.example.com -c shared_buffers=4GB
sql db02.example.com postgres <<<"CREATE DATABASE app;"
workload db02.example.com app 10 10
collect db02.example.com

say "collecting analytics01.example.com: default settings"
start_host analytics01.example.com
sql analytics01.example.com postgres <<<"CREATE DATABASE warehouse;"
workload analytics01.example.com warehouse 20 5
collect analytics01.example.com

# The other hosts only appear in the list, so they are assessed with
# no provider at all: the claude provider with no key never calls out.
say "building and starting the analyst without a provider"
RADAR_ANALYST_AI_PROVIDER=claude ANTHROPIC_API_KEY= \
    "${COMPOSE[@]}" up -d --build --wait >/dev/null

# upload ARCHIVE: prints the upload id once its assessment is done.
upload() {
    local reply upload_id job_id state
    reply="$(curl -fsS -F "file=@$1" "$BASE/api/uploads")"
    upload_id="$("$PY" -c 'import json,sys; print(json.load(sys.stdin)["upload_id"])' <<<"$reply")"
    job_id="$("$PY" -c 'import json,sys; print(json.load(sys.stdin)["job_id"])' <<<"$reply")"
    for _ in $(seq 1 120); do
        state="$(curl -fsS "$BASE/api/jobs/$job_id" \
            | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["state"])')"
        case "$state" in
            done) echo "$upload_id"; return 0 ;;
            failed) die "the assessment of $(basename "$1") failed" ;;
        esac
        say "  $(basename "$1"): $state" >&2
        sleep 5
    done
    die "the assessment of $(basename "$1") did not finish in 10 minutes"
}

for archive in "$WORK"/radar-*.zip; do
    say "assessing $(basename "$archive")"
    upload "$archive" >/dev/null
done

say "restarting the analyst with the provider from .env"
"${COMPOSE[@]}" up -d --wait >/dev/null
say "assessing $(basename "$SHOWCASE")"
SHOWCASE_ID="$(upload "$SHOWCASE")"

# A missing or refused credential still yields an assessment, with
# every brief unavailable; pictures of that would undersell it.
if curl -fsS "$BASE/api/uploads/$SHOWCASE_ID/assessment" \
    | grep -q 'Brief unavailable'; then
    die "the provider in .env wrote no briefs; check its credential"
fi

say "capturing"
node "$ROOT/capture-screenshots.mjs" \
    "$BASE" "$SHOWCASE_ID" "$SHOWCASE_CATEGORY" "$OUT"
say "done; review docs/img/console-*.jpg before committing them"
