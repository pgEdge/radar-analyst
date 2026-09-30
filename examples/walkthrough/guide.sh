#!/usr/bin/env bash
#
# Guided tour of pgEdge Radar Analyst for a first look. Starts the
# analyst, opens its console in the browser, and walks through taking
# a radar collection of a PostgreSQL host and assessing it there.
#
#   bash examples/walkthrough/guide.sh          the tour
#   bash examples/walkthrough/guide.sh --down   take it all down again
#
# Docker with the Compose plugin is all it needs. It runs the
# docker-compose.yml at the repository root, so a .env beside that
# file applies. The tour itself never stops anything; --down is the
# one way it removes the containers, and with them every assessment
# and archive, after asking.
#
# Environment:
#   WALKTHROUGH_BUILD=1           build the analyst from this checkout
#                                 (docker-compose.build.yml) instead of
#                                 pulling the published image, so the
#                                 tour shows the code you have, not the
#                                 last release
#   WALKTHROUGH_NO_BROWSER=1      print the console's address instead
#                                 of opening it
#   WALKTHROUGH_NONINTERACTIVE=1  no prompts: every question takes
#                                 its default, and any failure exits
#                                 non-zero
#   BROWSER                       the command to open URLs with, when
#                                 the platform's own is not wanted

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE=(docker compose -f "$ROOT/docker-compose.yml")
UP_FLAGS=()
UP_SHOWN="docker compose up -d --wait"
if [ "${WALKTHROUGH_BUILD:-0}" = 1 ]; then
    COMPOSE+=(-f "$ROOT/docker-compose.build.yml")
    UP_FLAGS=(--build)
    UP_SHOWN="docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build --wait"
fi
NONINTERACTIVE="${WALKTHROUGH_NONINTERACTIVE:-0}"
NO_BROWSER="${WALKTHROUGH_NO_BROWSER:-0}"
RELEASES="https://github.com/pgEdge/radar/releases"

BOLD='\033[1m'
TEAL='\033[38;5;30m'
ORANGE='\033[38;5;172m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
DIM='\033[2m'
RESET='\033[0m'

header()  { echo -e "\n${BOLD}${TEAL}$1${RESET}\n"; }
explain() { echo -e "$1"; }
info()    { echo -e "${GREEN}$1${RESET}"; }
warn()    { echo -e "${YELLOW}$1${RESET}"; }
show_cmd() { echo -e "\n${ORANGE}\$ $1${RESET}"; }
die()     { echo -e "${RED}$1${RESET}" >&2; exit 1; }

pause() {
    [ "$NONINTERACTIVE" = 1 ] && return 0
    echo ""
    read -rp "${1:-Press Enter to continue...}" </dev/tty
    echo ""
}

# ask_yes <question>: true unless the answer starts with n. A bare
# Enter, and a non-interactive run, mean yes.
ask_yes() {
    [ "$NONINTERACTIVE" = 1 ] && return 0
    local answer
    echo ""
    read -rp "$1 [Y/n]: " answer </dev/tty
    [[ ! "$answer" =~ ^[Nn] ]]
}

# The browser is handed the URL and never waited for, so a launcher
# that blocks cannot stall the tour. $BROWSER wins when set; on
# Linux, `open` is the console tool openvt, so xdg-open is used there
# and only under a graphical session.
open_url() {
    local url="$1"
    if [ "$NO_BROWSER" = 1 ]; then
        explain "  Open ${BOLD}$url${RESET} in your browser."
        return 0
    fi
    if [ -n "${BROWSER:-}" ]; then
        ( "$BROWSER" "$url" >/dev/null 2>&1 & )
    elif [ "$(uname -s)" = Darwin ]; then
        ( open "$url" >/dev/null 2>&1 & )
    elif [ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ] \
        && command -v xdg-open >/dev/null 2>&1; then
        ( xdg-open "$url" >/dev/null 2>&1 & )
    else
        explain "  Open ${BOLD}$url${RESET} in your browser."
        return 0
    fi
    info "  Opened $url"
}

# ── Arguments ───────────────────────────────────────────────────────

MODE=tour
case "${1:-}" in
    "") ;;
    --down) MODE=down ;;
    *) die "Unknown argument: $1. Run with no argument for the tour, or --down to remove everything it set up." ;;
esac

# ── Takedown ────────────────────────────────────────────────────────

if [ "$MODE" = down ]; then
    header "pgEdge Radar Analyst: take the tour down"
    command -v docker >/dev/null 2>&1 \
        || die "docker is not installed: https://docs.docker.com/get-docker/"
    explain "This removes the analyst's containers and its volumes: every"
    explain "assessment and every uploaded archive goes with them, and the sample"
    explain "archive in this directory, if there is one. There is no undo."
    if [ "$NONINTERACTIVE" != 1 ]; then
        echo ""
        read -rp "Delete everything? [y/N]: " answer </dev/tty
        [[ "$answer" =~ ^[Yy] ]] || { info "Nothing removed."; exit 0; }
    fi
    show_cmd "docker compose down -v"
    "${COMPOSE[@]}" down -v >/dev/null 2>&1 || die "docker compose down -v failed"
    rm -f "$PWD/radar-sample.zip"
    info "Removed the containers, the volumes, and with them every assessment and archive."
    exit 0
fi

# ── Prerequisites ───────────────────────────────────────────────────

header "pgEdge Radar Analyst: guided walkthrough"
explain "This tour starts the analyst, opens its console in your browser, and"
explain "shows you how to take a radar collection of a PostgreSQL host and"
explain "assess it. Docker is all it needs, and it takes a few minutes."

command -v docker >/dev/null 2>&1 \
    || die "docker is not installed: https://docs.docker.com/get-docker/"
docker info >/dev/null 2>&1 \
    || die "Docker is installed but not running, or not reachable by your user."
docker compose version >/dev/null 2>&1 \
    || die "The docker compose plugin is missing: https://docs.docker.com/compose/install/"

# ── Step 1: start ───────────────────────────────────────────────────

header "Step 1: start the analyst"
explain "The analyst is two containers: the analyst itself, and a PostgreSQL it"
explain "keeps its results in. The console is reachable only from this machine,"
explain "and the database only from the analyst."
[ -f "$ROOT/.env" ] && explain "\n  ${DIM}Using the settings in $ROOT/.env${RESET}"
if [ "${WALKTHROUGH_BUILD:-0}" = 1 ]; then
    explain "  ${DIM}Building the analyst from this checkout rather than pulling the published image${RESET}"
fi

if [ -n "$("${COMPOSE[@]}" ps -q --status running app 2>/dev/null)" ]; then
    echo ""
    info "The analyst is already running, so there is nothing to start."
else
    pause "Press Enter to start it..."
    show_cmd "$UP_SHOWN"
    if ! out="$("${COMPOSE[@]}" up -d "${UP_FLAGS[@]}" --wait 2>&1)"; then
        printf '%s\n' "$out" | tail -15
        if printf '%s' "$out" | grep -qiE 'denied|unauthorized|authentication required'; then
            echo ""
            explain "The images are in the GitHub Container Registry. Sign in with a"
            explain "token that can read packages, then run the tour again:"
            explain ""
            explain "    docker login ghcr.io"
        fi
        die "docker compose up failed"
    fi
    info "  The analyst is running."
fi

bind="$("${COMPOSE[@]}" port app 8080 2>/dev/null | tail -1)"
[ -n "$bind" ] || die "Could not find the console's published port."
BASE="http://localhost:${bind##*:}"

# ── Step 2: the console ─────────────────────────────────────────────

header "Step 2: the console"
explain "The console is at ${BOLD}$BASE/${RESET}: an upload area for radar"
explain "archives and, below it, the most recent assessments. On a fresh"
explain "install that list is empty."
pause "Press Enter to open it in your browser..."
open_url "$BASE/"

# ── Step 3: a collection ────────────────────────────────────────────

header "Step 3: take a radar collection"
explain "A radar archive is what the analyst assesses. Radar collects it on"
explain "the PostgreSQL host: metadata about the machine and the server, never"
explain "table contents or query results."
explain ""
explain "  1. Download the binary for the host's platform from"
explain "     ${BOLD}$RELEASES${RESET}"
explain "     ${DIM}radar-linux-amd64, radar-linux-arm64, radar-darwin-amd64, radar-darwin-arm64${RESET}"
explain ""
explain "  2. On the host, as root, connecting as a superuser or as a role with"
explain "     pg_monitor. Add -h and -p if the server is not on the local socket."
explain ""
explain "       ${ORANGE}chmod +x radar-linux-amd64 && mv radar-linux-amd64 radar${RESET}"
explain "       ${ORANGE}sudo PGPASSWORD='...' ./radar -d mydb -U postgres${RESET}"
explain ""
explain "  3. A minute or two later it has written one file beside you,"
explain "     ${BOLD}radar-<hostname>-<timestamp>.zip${RESET}. Copy it to this machine."
pause

# ── Step 4: assess it ───────────────────────────────────────────────

header "Step 4: assess it"
explain "Drop the archive on the console's upload area, or click the area to"
explain "choose it, and press Upload. The console shows the archive being read"
explain "and each category being assessed, then moves to the finished"
explain "assessment on its own."
explain ""
explain "An assessment is five categories, each with a verdict, the findings"
explain "behind it, and a brief, and one verdict for the host: the worst of the"
explain "five. The findings are worked out from the archive alone and always"
explain "come back. The written briefs come from a provider, which is optional:"
explain "without one, each brief reads as unavailable. To add one, put a"
explain "credential in a .env file beside docker-compose.yml and start the"
explain "analyst again; examples/compose.env is a commented .env file to start"
explain "from. Then press Assess again on an assessment made before, and its"
explain "briefs are written from the stored archive."
echo ""
explain "No PostgreSQL to hand yet? The analyst can write a small sample archive"
explain "to try with: one database and a handful of settings, enough to see an"
explain "assessment happen. A real collection gives a real assessment."
if ask_yes "Write a sample archive to try with?"; then
    "${COMPOSE[@]}" exec -T app python -m radar_analyst.tests.make_sample_zip \
        /tmp/radar-sample.zip >/dev/null 2>&1 \
        || die "Could not write the sample archive."
    "${COMPOSE[@]}" cp app:/tmp/radar-sample.zip "$PWD/radar-sample.zip" >/dev/null 2>&1 \
        || die "Could not copy the sample archive out of the container."
    info "  Sample archive: $PWD/radar-sample.zip"
    explain "  Drop it on the upload area to see an assessment now."
fi
pause

# ── Step 5: kept, and stopped ───────────────────────────────────────

header "Step 5: your assessments stay"
explain "Assessments, and the archives behind them, are kept in Docker volumes."
explain "They survive docker compose down, and pulling a newer image. Each"
explain "entry in the console's list has a delete button, which asks you to"
explain "confirm and then for the admin token. Unless you set"
explain "RADAR_ANALYST_ADMIN_TOKEN in .env, the analyst wrote one for you on"
explain "first start:"
show_cmd "docker compose exec app cat /data/admin-token"
echo ""
explain "The analyst stays running until you say otherwise:"
explain ""
explain "  docker compose stop      pause it; docker compose start brings it back"
explain "  docker compose down      remove the containers, keep every assessment"
explain ""
explain "An assessment that was running when the analyst stopped is marked"
explain "failed when it starts again; open it and press Assess again."
explain ""
explain "Done exploring? This removes the containers AND every assessment and"
explain "archive, after asking. There is no undo:"
explain ""
explain "  bash examples/walkthrough/guide.sh --down"
echo ""
explain "docs/index.md covers providers, backups, and using a PostgreSQL you"
explain "already run."
echo ""
info "The console is at $BASE/"
