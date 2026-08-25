# pgEdge Radar Analyst

> Internal service that reads
> [radar](https://github.com/pgEdge/radar) diagnostic archives,
> checks them against deterministic rules, writes a brief per
> diagnostic category, and serves the assessment over a JSON API
> with a replaceable Astro console.

Not for public distribution. Deployment target is `docker compose up`
(or the published container image) alongside a PostgreSQL instance.

For the engineering design (module layering, pipeline stages, adapter
architecture, deferred work) see [ARCHITECTURE.md](ARCHITECTURE.md).

## What it does

1. Accepts an upload of a radar archive via `POST /api/uploads`.
2. Stores the archive in a pluggable blob store (local filesystem
   now, S3 or seaweedfs-compatible later; PostgreSQL only keeps the
   URL).
3. Parses known file kinds in the archive into typed records, and
   tracks any unparsed archive paths in a coverage-canary list so new
   radar collectors never drop out of the assessment silently.
4. Runs a deterministic rule engine (~75 rules across 10 rule
   modules) that produces findings per category, covering host
   tuning, PG configuration, HBA security, replication health,
   workload anomalies, I/O saturation, and per-database metrics.
5. Calls an LLM per category (Claude, Gemini, OpenAI or any
   OpenAI-compatible endpoint, or local Ollama) to write that
   category's brief, with per-provider graceful degradation and
   Anthropic prompt caching on the system block.
6. Streams progress to the browser via Server-Sent Events while the
   job runs.
7. Presents the assessment in a minimal Astro console that follows
   the [pgEdge visual-identity pack](https://github.com/pgEdge/). The
   console is a pure consumer of the JSON API and can be swapped for
   anything else that speaks the same endpoints.

All metadata, findings, and briefs live in a dedicated `radar` schema
inside PostgreSQL.

## Categories

Each category is one LLM call and answers one question a DBA asks
during a health check:

1. Host & OS: is the machine sized and tuned for a DB workload?
2. PostgreSQL Configuration: are the settings appropriate for this
   hardware and workload?
3. Workload: what is the server doing right now, and is anything
   stuck?
4. Internals & I/O Health: are the background processes, WAL
   pipeline, and storage I/O healthy?
5. Replication: is replication safe, caught up, and retention-sound?

The assessment's own verdict is the worst of the five category
verdicts. A category the archive carries no data for reads `UNKNOWN`
and never drags the roll-up down.

Additionally, each user database gets its own brief when at least one
finding fires or the database has meaningful activity (backends > 0
or commits + rollbacks > 100). Idle databases with no findings get a
static "no issues" card.

## Architecture

```
┌──────────────┐    POST /api/uploads     ┌──────────────┐
│ Astro console│ ───────────────────────► │  FastAPI     │
│ or any JSON  │    SSE /api/jobs/.../    │  service     │
│ client       │ ◄─────────── events      │              │
└──────────────┘                          └──┬────────┬──┘
                                             │        │
                             ┌───────────────┘        └────────────────┐
                             ▼                                         ▼
                    ┌──────────────┐                          ┌────────────────┐
                    │ Blob store   │                          │ PostgreSQL     │
                    │ localfs / S3 │                          │ `radar` schema │
                    └──────────────┘                          └────────────────┘
                             │
                             ▼
            ┌────────────────────────────────────────────┐
            │  Orchestrator (asyncio.Task per upload)    │
            │                                            │
            │  walk ─► parse ─► rules ─► per-category    │
            │           (findings)       briefing        │
            │                                            │
            └────────────────────────────────────────────┘
                                   │
                                   ▼
                     ┌──────────────────────────────┐
                     │ AI adapter                   │
                     │ claude                       │
                     │ gemini                       │
                     │ openai (+ compatible)        │
                     │ local                        │
                     │ mock (RADAR_ANALYST_TEST=1)  │
                     └──────────────────────────────┘
```

## Quick start (Docker)

Provide at least one AI provider in a `.env` file, then start the
stack:

```bash
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env
docker compose up -d
```

Open [http://localhost:8080/](http://localhost:8080/) and drag a
`radar-*.zip` onto the upload area.

## Development setup

Requires Python 3.11+, Node.js 20+, Docker.

```bash
# Backend: create a venv and install in editable mode
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'

# Frontend
cd web && npm install && npm run dev        # :4321
# In another shell, run the backend:
RADAR_ANALYST_STATE_DB_URL=postgresql://... \
  RADAR_ANALYST_BLOB_DIR=./data/blobs \
  python -m radar_analyst                   # :8080
```

The Astro dev server proxies `/api/*` and `/readyz` to the backend on
`:8080`, so same-origin assumptions hold.

## Environment variables

The following table describes every setting the service reads. Note
that `RADAR_ANALYST_STATE_DB_URL` points at the analyst's own state
database, never at the PostgreSQL server being assessed: the analyst
works from the uploaded archive and holds no credentials for the
assessed host.

| Variable | Default | Purpose |
|---|---|---|
| `RADAR_ANALYST_LISTEN` | `127.0.0.1:8080` | listen address (`host:port`, or a bare port). Loopback by default; set `0.0.0.0:8080` to accept connections from other hosts. A malformed value stops startup rather than opening an unexpected port. |
| `RADAR_ANALYST_STATE_DB_URL` | _(required)_ | PostgreSQL URL for the analyst's own state; `sslmode=prefer` |
| `RADAR_ANALYST_BLOB_DIR` | `./data/blobs` | local-filesystem blob root |
| `RADAR_ANALYST_MAX_UPLOAD_BYTES` | `524288000` (500 MiB) | upload size ceiling; real archives heavy with per-database time-series land at 100-150 MiB compressed |
| `RADAR_ANALYST_ADMIN_TOKEN` | _(unset)_ | shared bearer token required for `DELETE /api/uploads/{id}`; deletes return 503 while unset. There is no role separation: every authenticated caller is treated as admin. |
| `RADAR_ANALYST_AI_PROVIDER` | `claude` | `claude` / `gemini` / `openai` / `local` / `mock` |
| `ANTHROPIC_API_KEY` | _(unset)_ | Claude adapter |
| `GOOGLE_API_KEY` / `GEMINI_API_KEY` | _(unset)_ | Gemini adapter |
| `OPENAI_API_KEY` | _(unset)_ | OpenAI adapter; required even for compatible servers that ignore it |
| `OPENAI_BASE_URL` | _(OpenAI's own endpoint)_ | point the OpenAI adapter at a compatible server |
| `OPENAI_MODEL` | `gpt-5.6-luna` | model name; compatible servers need their own |
| `RADAR_ANALYST_OLLAMA_HOST` | `http://localhost:11434` | Ollama server URL |
| `RADAR_ANALYST_OLLAMA_MODEL` | `gemma4:e4b` | Ollama model name |
| `RADAR_ANALYST_OLLAMA_CONCURRENCY` | `3` | max concurrent Ollama calls |
| `RADAR_ANALYST_TEST` | _(unset)_ | enables the `mock` AI provider |
| `RADAR_ANALYST_LOG_LEVEL` | `INFO` | log level |

### Listen address

The analyst is a local tool, so it binds `127.0.0.1` unless told
otherwise. A bare port or a `:port` value keeps the loopback host:

```bash
RADAR_ANALYST_LISTEN=9000          # 127.0.0.1:9000
RADAR_ANALYST_LISTEN=:9000         # 127.0.0.1:9000
RADAR_ANALYST_LISTEN=0.0.0.0:8080  # every interface
RADAR_ANALYST_LISTEN='[::]:8080'   # every interface, IPv6
```

Binding anything other than loopback logs a warning at startup,
because it makes the analyst reachable from other machines.

Inside the container the service binds `0.0.0.0`, since a
container's own loopback is not reachable from the host. What keeps
it local there is the compose port publish, `127.0.0.1:8080:8080`.
Remove that prefix and the analyst is exposed on every interface of
the host.

### Default models

The following table lists the model each provider uses and how to
override it:

| Provider | Default model | Override |
|---|---|---|
| `claude` | `claude-sonnet-5` | construct `ClaudeAdapter(model=...)` |
| `gemini` | `gemini-3.7-flash` | construct `GeminiAdapter(model=...)` |
| `openai` | `gpt-5.6-luna` | `OPENAI_MODEL` |
| `local` | `gemma4:e4b` | `RADAR_ANALYST_OLLAMA_MODEL` |

Claude defaults to Sonnet rather than Opus because one upload costs a
call per category plus a call for every active database, and the
prompts carry structured facts rather than open-ended reasoning.

### OpenAI-compatible endpoints

The `openai` provider talks plain chat completions, so it also drives
any server that speaks that API (vLLM, LM Studio, llama.cpp,
OpenRouter, Groq, Ollama's `/v1` endpoint). Set the base URL and the
server's own model name, and set a key even for a server that ignores
it, because the SDK requires one:

```bash
export RADAR_ANALYST_AI_PROVIDER=openai
export OPENAI_BASE_URL=http://localhost:8000/v1
export OPENAI_API_KEY=unused
export OPENAI_MODEL=Qwen/Qwen3-32B
```

`Request.cache_static` has no effect on this adapter, because OpenAI
applies its prompt-cache discount on its own and offers no
per-request flag to set.

## Running tests

Run the unit and integration suites during development, and the full
local CI before committing:

```bash
# unit + integration (uses testcontainers-python for real Postgres)
.venv/bin/pytest -v -m 'not e2e'

# full local CI (lint, type, unit, Astro build, Docker, e2e in Docker)
./run-ci-local.sh
```

The radar-format validation suite
(`tests/test_real_radar_zip.py`) runs against an archive generated
by `tests/make_sample_zip.py`; point `RADAR_SAMPLE_ZIP` at a real
radar zip to validate against live collector output instead.

## API surface

The following table describes every endpoint the service exposes:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/uploads` | multipart upload; returns `{upload_id, job_id}`; non-zip bodies are rejected with 415 |
| `GET` | `/api/uploads?limit=&offset=` | list prior uploads |
| `GET` | `/api/uploads/{id}` | upload metadata |
| `DELETE` | `/api/uploads/{id}` | delete upload and blob (204 No Content) |
| `GET` | `/api/uploads/{id}/snapshot` | parsed host/PG context and coverage canary |
| `GET` | `/api/uploads/{id}/assessment` | roll-up `verdict` plus the `briefs` array; each brief carries its verdict and a `sources` list of archive paths |
| `GET` | `/api/uploads/{id}/files` | inventory of every entry in the uploaded radar archive |
| `GET` | `/api/uploads/{id}/files/{path}` | stream a single entry from the radar archive (whitelisted by inventory) |
| `GET` | `/api/jobs/{id}` | current job state |
| `GET` | `/api/jobs/{id}/events` | Server-Sent Events progress stream |
| `GET` | `/api/config` | provider inventory and availability |
| `GET` | `/healthz` | liveness |
| `GET` | `/readyz` | readiness (DB pool attached) |

## Conventions

See [CLAUDE.md](CLAUDE.md). In summary: TDD is a hard requirement,
code is linted with `flake8 --ignore F722,W503
--max-line-length=79 --max-complexity=8`,
tests live in `src/radar_analyst/tests/`, all
DB tables live in the `radar` schema, and commits are short and
imperative with no AI attribution.

## Licence

See [LICENCE](LICENCE). The PostgreSQL Licence.
