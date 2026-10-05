# Examples

This directory contains a template for the analyst's settings and an
interactive guide to the analyst. The following table describes each example:

| Path | Purpose |
|---|---|
| `compose.env` | Provides a commented `.env` file for `docker compose up -d --wait`. Every setting in the file is optional. |
| `walkthrough/guide.sh` | Runs a guided first look at the analyst, from starting the analyst to assessing a radar collection. |

To use the settings template, copy `compose.env` to `.env` beside
`docker-compose.yml` and uncomment the settings that you need.

The guide starts the analyst with the `docker-compose.yml` at the repository
root. The guide then opens the console in a browser and explains how to take
and assess a radar collection. The guide needs only
[Docker](https://docs.docker.com/get-started/get-docker/) with the
[Compose plugin](https://docs.docker.com/compose/install/). The guide runs the
published image, unless `WALKTHROUGH_BUILD=1` asks for a build from the
checkout. The guide never stops an analyst that is already running. The
`guide.sh --down` command is the only way that the guide removes anything, and
the command removes the volumes too. The command asks for confirmation first,
unless `WALKTHROUGH_NONINTERACTIVE=1` is set. The
[walkthrough page](../docs/walkthrough.md) describes the same tour by hand.
