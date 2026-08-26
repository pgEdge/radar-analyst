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
