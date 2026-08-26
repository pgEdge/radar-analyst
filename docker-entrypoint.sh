#!/bin/sh
#
# Prepare the data volume, then drop privileges and start the
# analyst. Root is used only to make a freshly mounted volume
# writable; the service itself runs as the unprivileged `radar`
# user. Running the container with --user skips the whole block,
# since there is then nothing to drop to and nothing that could
# chown.

set -e

DATA_DIR="${RADAR_ANALYST_DATA_DIR:-/data}"

if [ "$(id -u)" = "0" ]; then
    mkdir -p "$DATA_DIR"
    # A named volume inherits the image's ownership and needs
    # nothing. A bind mount arrives owned by whoever made the host
    # directory, so it is claimed once and matches on every later
    # start.
    if [ "$(stat -c %u "$DATA_DIR")" != "$(id -u radar)" ]; then
        chown -R radar:radar "$DATA_DIR"
    fi
    exec setpriv --reuid=radar --regid=radar --clear-groups "$0" "$@"
fi

exec "$@"
