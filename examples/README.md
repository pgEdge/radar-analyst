# Example configurations

One file per deployment shape. Copy the one you want to `.env` next
to `docker-compose.yml`, or point a systemd unit at it, and edit the
values.

| File | Deployment |
|---|---|
| `compose.env` | `docker compose up -d`, the analyst with its own PostgreSQL service |
| `external-postgres.env` | the analyst against a PostgreSQL you already run |
| `local-model.env` | the analyst with a local Ollama server, no credential leaving the machine |

Every setting is optional except `RADAR_ANALYST_STATE_DB_URL`, which
`docker-compose.yml` sets for you. Without a provider credential the
findings and verdicts still come back and the briefs are omitted.

`walkthrough/guide.sh` is different: a guided tour for a first
look. It starts the analyst with the `docker-compose.yml` at the
repository root, opens the console in the browser, and walks through
taking a radar collection and assessing it. It never stops an
analyst it finds already running; `guide.sh --down` is the one way it
removes anything, and that takes the volumes too, after asking. It
needs only Docker. It pulls the published image; set
`WALKTHROUGH_BUILD=1` to build the analyst from the checkout instead,
which is how to see uncommitted or unreleased changes. The
user-facing page is `docs/walkthrough.md`;
`tests/test_walkthrough_guide.py` runs the script against a stub
`docker`.
