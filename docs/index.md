# pgEdge Radar Analyst

pgEdge Radar Analyst reads a
[radar](https://github.com/pgEdge/radar) diagnostic archive and
returns an assessment of the PostgreSQL host it came from. The
analyst checks the archive against deterministic rules and writes a
short brief for each diagnostic category, then serves the result over
a JSON API and a browser console.

## What you need

Running the analyst requires:

- Docker and Docker Compose.
- one configured provider for the briefing step, chosen from the
  list below.

The analyst supports these providers:

- Anthropic, by setting `ANTHROPIC_API_KEY`.
- Google AI Studio, by setting `GOOGLE_API_KEY`.
- OpenAI, by setting `OPENAI_API_KEY`. Point `OPENAI_BASE_URL` at
  any OpenAI-compatible server to use one instead.
- A local Ollama server, reachable at `RADAR_ANALYST_OLLAMA_HOST`.

## Quick start

Write a provider credential into a `.env` file next to
`docker-compose.yml`, then bring the stack up:

```bash
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env
docker compose up -d
```

Open [http://localhost:8080/](http://localhost:8080/) and drag a
`radar-*.zip` onto the upload area. The analyst reads the archive,
applies the rules, and returns the assessment in the console. A
file that is not a zip archive is refused at upload time.

The analyst listens on the loopback interface only, so nothing on
your network can reach it. To open it to other machines, set
`RADAR_ANALYST_LISTEN` to `0.0.0.0:8080` and publish the container
port without the `127.0.0.1` prefix in `docker-compose.yml`.

## What you get

Every archive is assessed against five diagnostic categories:

- Host and OS asks whether the machine is sized and tuned for a
  database workload.
- PostgreSQL Configuration asks whether the settings suit this
  hardware and this workload.
- Workload asks what the server is doing and whether anything is
  stuck.
- Internals and I/O Health asks whether the background processes,
  the WAL pipeline, and storage I/O are sound.
- Replication asks whether replication is safe, caught up, and
  retention-sound.

Each category carries a verdict of HEALTHY, WARNING, or CRITICAL,
the deterministic findings that verdict rests on, and a brief that
reads those findings back in prose. The assessment's own verdict is
the worst of the five. Each user database gets its own brief when
findings or meaningful activity are present.

Findings and verdicts are deterministic and reproducible from the
archive alone. If the configured provider is unreachable the briefs
are omitted, and the findings and verdicts still come back.

## Environment variables

The following table describes the settings the analyst reads from
its environment. The README documents the full list.

| Variable | Default | Purpose |
|---|---|---|
| `RADAR_ANALYST_LISTEN` | `127.0.0.1:8080` | listen address; loopback by default, set `0.0.0.0:8080` to allow other hosts |
| `RADAR_ANALYST_STATE_DB_URL` | (required) | PostgreSQL URL for the analyst's own state; never the assessed server |
| `RADAR_ANALYST_AI_PROVIDER` | `claude` | `claude`, `gemini`, `openai`, or `local` |
| `RADAR_ANALYST_BLOB_DIR` | `/data/blobs` | where uploaded archives are kept |
| `RADAR_ANALYST_ADMIN_TOKEN` | (unset) | bearer token required to delete an upload from the console; the delete button returns an error while unset |
| `ANTHROPIC_API_KEY` | (unset) | required when the provider is `claude` |
| `GOOGLE_API_KEY` | (unset) | required when the provider is `gemini` |
| `OPENAI_API_KEY` | (unset) | required when the provider is `openai`, including for compatible servers that ignore the value |
| `OPENAI_BASE_URL` | OpenAI's own endpoint | set to reach an OpenAI-compatible server, for example `http://localhost:8000/v1` |
| `OPENAI_MODEL` | `gpt-5.6-luna` | model name; a compatible server needs its own, for example `Qwen/Qwen3-32B` |
| `RADAR_ANALYST_OLLAMA_HOST` | `http://localhost:11434` | used when the provider is `local` |
| `RADAR_ANALYST_OLLAMA_MODEL` | `gemma4:e4b` | used when the provider is `local`; needs roughly 10 GB of VRAM to run fully on GPU |

## Licence

See [LICENCE](LICENCE.md). The PostgreSQL Licence.
