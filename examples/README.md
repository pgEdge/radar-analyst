# Examples

This directory contains a template for the analyst's settings and an
interactive guide to the analyst. The following table describes each example in
this directory:

| Path | Purpose |
|---|---|
| `compose.env` | This file provides a commented `.env` file for `docker compose up -d --wait`. Every setting in the file is optional. |
| `walkthrough/guide.sh` | This script runs a guided first look at the analyst, from starting the analyst to assessing a radar collection. |

To use the settings template, copy `compose.env` to `.env` beside
`docker-compose.yml` and uncomment the settings that you need.

The guide starts the analyst with the `docker-compose.yml` at the repository
root. The guide then opens the console in a browser and explains how to take
and assess a radar collection. The guide needs only
[Docker](https://docs.docker.com/get-started/get-docker/) with the
[Compose plugin](https://docs.docker.com/compose/install/). The guide runs the
published image, unless `WALKTHROUGH_BUILD=1` asks for a build from the
checkout. Without that setting, the guide reuses an analyst that the clone's
compose file already runs. The `guide.sh --down` command is the only way that
the guide removes anything, and the command removes the volumes too. The
command asks for confirmation first, unless you set
`WALKTHROUGH_NONINTERACTIVE=1`. The [walkthrough page](../docs/walkthrough.md)
describes the same steps by hand.
