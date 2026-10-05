# pgEdge Radar Analyst Architecture

This document describes how the analyst is built: its parts, the
path an archive takes through them, and the reasons for each choice.
[README.md](README.md) is the user guide, [docs/api.md](docs/api.md)
describes the API, and [CLAUDE.md](CLAUDE.md) holds the rules every
change follows.

## Overview

radar ([github.com/pgEdge/radar](https://github.com/pgEdge/radar))
collects PostgreSQL and Linux system state from a host into a zip
archive and analyses nothing. The analyst reads that archive, checks
it against deterministic rules, asks a language model for a brief per
diagnostic category, and serves the assessment over a JSON API to the
console or any other client.

```
┌──────────────┐    POST /api/uploads     ┌──────────────┐
│ Astro console│ ───────────────────────► │  FastAPI     │
│ or any JSON  │   /api/jobs/{id}/events  │  service     │
│ client       │ ◄──── progress stream    │              │
└──────────────┘                          └──┬────────┬──┘
                                             │        │
                             ┌───────────────┘        └────────────────┐
                             ▼                                         ▼
                    ┌──────────────┐                          ┌────────────────┐
                    │ Blob store   │                          │ PostgreSQL     │
                    │ filesystem   │                          │ `radar` schema │
                    └──────────────┘                          └────────────────┘
                             │
                             ▼
            ┌────────────────────────────────────────────┐
            │  Orchestrator (asyncio.Task per job)       │
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

An assessment takes these steps:

1. The client posts the archive to `POST /api/uploads`. Starlette
   spools the multipart body to a temporary file before the route
   runs. The route copies it into the blob store, refusing anything
   that is not a zip or is larger than `RADAR_ANALYST_MAX_UPLOAD_BYTES`,
   records the upload and a queued job, hands the job to the runner,
   and answers `201` with the upload and job ids. The runner runs at
   most four jobs at once, and the rest wait as `queued`.
2. The client follows the job on `GET /api/jobs/{id}/events`, a
   stream of Server-Sent Events fed by the in-process hub in
   `server/sse.py`, which the task publishes to.
3. The task copies the archive from the blob store to a temporary
   file, walks and parses it, runs the rules, asks the provider for
   the briefs, and stores the snapshot, the findings, and the briefs.
4. Once the progress stream reports `done`, the client reads the
   result from `GET /api/uploads/{id}/assessment`.

`POST /api/uploads/{id}/assess` runs the task again for a stored
upload, after deleting its briefs and findings.
`GET /api/uploads/{id}/files` lists the archive's files, and
`GET /api/uploads/{id}/files/{path}` downloads one, allowing only the
paths in the inventory stored with the upload; each brief's sources,
from `analyze/sources.py`, link there. `DELETE /api/uploads/{id}`
needs the admin token as a bearer token. The analyst generates the
token on first start and keeps it in its data directory, answers 503
when it has none, and answers 401 when the token does not match.

At startup, before the server accepts connections, `main.py` opens the
pool, checks the encoding, applies the migrations, and marks any job a
previous process left unfinished as failed
(`store.jobs.fail_interrupted_jobs`), because the task running it is
gone. It then builds the provider named by `RADAR_ANALYST_AI_PROVIDER`
and starts the job runner.

## Guarantees

The code keeps four guarantees:

- Findings are deterministic. They are computed from the archive by
  `rules/` and, for the per-database checks, by the orchestrator;
  no adapter, and no code downstream of one, ever makes one. Anything
  a model notices beyond the rules stays in the brief's prose.
- Verdicts survive a provider outage.
  `rules.base.apply_finding_floor` runs after every provider call,
  successful or not, so a briefed category's verdict is never better
  than its worst finding, and a failed call leaves the verdict to the
  findings alone. An assessment always has its findings and
  verdicts; only briefs can be missing. `test_degraded_mode.py` pins
  this.
- `UNKNOWN` never outranks evidence.
  `analyze.assessment.rollup_verdict` takes the worst of the category
  verdicts and the assessed databases' verdicts, which the upload
  listing query gathers for the list, the single upload, and the
  assessment alike. `UNKNOWN`, meaning a category was not collected,
  never counts as worse than a verdict drawn from data.
- The state database is never the assessed server. The analyst works
  from the uploaded archive and holds no credentials for the host it
  came from.

## Stack

The following table lists each technology choice and the reason for
it:

| Concern | Choice | Reason |
|---|---|---|
| Language | Python 3.11 or later | The work is in the rules and the prompts, not in CPU-bound parsing, and the provider SDKs are Python-first. |
| Web framework | FastAPI, with `sse-starlette` for the progress stream | Async throughout, OpenAPI built in, and `Depends()` for injecting test doubles. |
| Database driver | psycopg 3, async, with a connection pool | Async throughout. |
| Migrations | Plain SQL files in `store/migrations/`, applied in lexical order at startup | No migration framework. `radar.schema_migrations` records what has run, so a newer build applies only what an older data directory lacks. |
| Blob storage | The `BlobStore` Protocol, implemented for the local filesystem | PostgreSQL stores only an opaque URL, so another store needs no schema change. |
| Providers | Anthropic, Google Gemini, OpenAI and any OpenAI-compatible server, and Ollama | One adapter serves OpenAI and every compatible server, because they share the chat-completions request shape. |
| Console | Astro, built to static files | Everything it shows comes from the JSON API, so any client of the same endpoints can replace it. |
| Packaging | Hatchling with a build hook | `hatch_build.py` copies `web/dist/` into the package, so the wheel serves the console; without a console build, the server is API-only. |
| HTTP server | Plain uvicorn, without `[standard]` | One local user over loopback gains nothing from uvloop or httptools. |
| Listen address | `127.0.0.1:8080`, overridden by `RADAR_ANALYST_LISTEN` | Only a deliberate `0.0.0.0` opens the analyst to the network, and that logs a warning. The container binds `0.0.0.0`, and compose publishes the port on `127.0.0.1` only. |
| Distribution | A container image on GitHub Container Registry, run by docker-compose | A user runs `docker compose up -d`, installs nothing else, and configures the analyst through environment variables. |
| State storage | A PostgreSQL server named by `RADAR_ANALYST_STATE_DB_URL` | The compose stack's database and one the user already runs are the same code path. |
| PostgreSQL image | `ghcr.io/pgedge/pgedge-postgres:{16,17,18}-spock5-minimal` | The same image serves the tests, the end-to-end stack, and the deployment. The database holds only the analyst's state and does not use Spock. |

## State

Everything the analyst stores is in the `radar` schema, and every
query names the schema. The following table describes each table:

| Table | Holds |
|---|---|
| `radar.uploads` | Each archive's file name, size, host, collection time, file list, and blob store URL. |
| `radar.jobs` | Each assessment run's state, phase, start and finish times, error, and provider. |
| `radar.snapshots` | The parsed facts the console shows, as JSON: the host's details, the entries the classifier did not recognise, and each database's summary with its findings, brief, and verdict. |
| `radar.findings` | Each category finding's category, severity, rule id, title, and detail. |
| `radar.briefs` | Each category brief's verdict, provider, model, text, and token counts. |
| `radar.schema_migrations` | The migration files applied so far. |

## Code layout

The following table describes the packages in `src/radar_analyst/`:

| Package | Role |
|---|---|
| `server/` | The FastAPI app factory, the routes for uploads, jobs, and configuration, the hub behind the progress stream, and the mount that serves the console. |
| `store/` | The connection pool, the migration runner, one module per table, and the schema in `migrations/0001_init.sql`. |
| `blob/` | The `BlobStore` Protocol and its local filesystem implementation. |
| `archive/` | The zip walker, the path classifier, the safety caps, and the host and time read from an archive's name. |
| `parse/` | One parser per radar output, each returning typed data. |
| `rules/` | The deterministic rules, their registry, `Finding`, and the severity helpers. |
| `analyze/` | Parser dispatch, the facts sent to the provider, the categories, the orchestrator and the runner that starts it, and the roll-up verdict. |
| `ai/` | The `Analyzer` Protocol, the prompts, and one adapter per provider. |
| `model/` | The dataclasses the store returns. |
| `tests/` | One test module per production module. |

The following table describes the rest of the repository:

| Path | Role |
|---|---|
| `web/` | The console. |
| `Dockerfile`, `docker-entrypoint.sh` | The image, and the entrypoint that makes the data volume writable and then runs the analyst unprivileged. |
| `docker-compose.yml` | The deployment. `docker-compose.build.yml` builds the analyst from the checkout, and `docker-compose.test.yml` runs it with the mock provider. |
| `run-ci-local.sh` | Every CI step, in order. |
| `test-radar-analyst.sh` | The end-to-end test against the compose stack. |
| `check-archive-coverage.py` | Compares radar's collection tasks with the classifier. |
| `capture-screenshots.sh`, `capture-screenshots.mjs` | The console screenshots in `docs/img/`. |
| `hatch_build.py` | The build hook that puts the console into the wheel. |
| `examples/walkthrough/` | The guided walkthrough. |
| `docs/` | The documentation site. |

## Pipeline

A radar archive is far too large to send to a model, so three stages
reduce it first: extraction, rules, and briefing.

### Extraction

`archive/reader.py::classify` assigns each entry a kind from its
path, such as `pg.settings` or `sys.proc.meminfo`. A path it does not
know goes into the snapshot's `unknown_entries`, so a collector that
radar adds cannot drop out of an assessment unnoticed.
`check-archive-coverage.py` compares radar's collection tasks with
the classifier.

The parsers read entries through `open_entry(zip_path, entry_path,
*, max_bytes)`, a stream that raises `ZipSafetyError` as soon as the
caller reads past `max_bytes`, which is 500 MiB unless the caller
asks for less. `analyze/parsing.py` asks for 1 MiB and skips a
larger entry with a warning. No helper reads a whole entry into
memory, so every assumption about an entry's size is written where
it is made.

`analyze/parsing.py` dispatches each kind to its parser in `parse/`,
with per-database kinds kept per database. `parse/tsv.py` reads
radar's TSV output, which quotes like Python's `csv.QUOTE_MINIMAL`
with doubled quotes. `analyze/facts.py` turns the parsed data into
one compact facts block per category. The largest single saving is
`parse/sysctl.py`, which keeps only the kernel settings that matter
to PostgreSQL out of the thousand or more that `sysctl -a` prints.

### Rules

Rules run in two ways:

- Category rules are registered with `@register("<category>")` in
  the `REGISTRY` of `rules/base.py` and run by `run_for_category`.
- Per-database rules in `rules/pg_db.py` take one database's summary
  and are called by the orchestrator for each database.

Category findings are stored in `radar.findings` and per-database
findings in the snapshot. Both are sent to the provider with the
facts and set the floor for the verdict. The modules in `rules/`,
one per area, are the inventory of what is checked, with each rule's
thresholds in its code; the only per-database finding built outside
them is the orchestrator's checksum-failure check.

### Briefing

The five categories are defined in `analyze/categories.py`: Host &
OS, PostgreSQL Configuration, Workload, Internals & I/O Health, and
Replication. Each category that has facts gets one provider call; a
category without any is stored as `UNKNOWN` and gets none.

Each user database with at least one finding gets a call of its own,
and these run in parallel through `asyncio.gather`. A database
without findings gets a fixed "no issues observed" card and no call,
so a cluster of healthy databases costs nothing beyond the five
category calls. Template databases and databases that accept no
connections get no card, because no workload runs in them.

Every call has two parts:

- A system block, the same for every call in an assessment and
  cached where the provider supports it. The block casts the model
  as a PostgreSQL DBA, gives it the host's facts, such as the
  hostname and the PostgreSQL version, and tells it that anything
  inside `<user_data>` is data, never instructions.
- A user block with the findings and the facts, which
  `ai/prompts.py::wrap_user_data` wraps in `<user_data>`.

## Providers

`ai/base.py::Analyzer` is a runtime-checkable Protocol, so an adapter
needs the right methods and nothing else. The orchestrator calls
`analyze(Request)` and gets back a `Result` with the markdown, the
verdict, and the token counts. A failed call raises `AIError`, and
the orchestrator stores a "brief unavailable" row for
that category, which keeps its findings and verdict.

The following table describes each adapter:

| Adapter | Client | Notes |
|---|---|---|
| `claude.py` | `anthropic.AsyncAnthropic` | Marks the system block with `cache_control` for prompt caching. |
| `gemini.py` | `google.genai.Client` | Runs the client's synchronous call in a worker thread through `asyncio.to_thread`. |
| `openai_compat.py` | `openai.AsyncOpenAI`, chat completions | Serves OpenAI and any compatible server: `OPENAI_BASE_URL` picks the server and `OPENAI_MODEL` the model. The base URL is passed to the SDK explicitly, because the SDK accepts an empty `OPENAI_BASE_URL` from the environment and then sends requests to it. |
| `ollama.py` | `ollama.AsyncClient` | A semaphore, three calls by default, keeps parallel calls from overwhelming a local server. |
| `mock.py` | None | Returns a fixed `[HEALTHY]` brief. It is registered only when `RADAR_ANALYST_TEST=1`, for the end-to-end test, which needs no key. |

`ai/__init__.py::providers()` lists the providers, and `make(name)`
builds one. `GET /api/config` lists them too, with the `reason` from
`unavailable_reason()` for any that cannot run.

## Console

`web/` is an Astro project with no UI framework and no component
library; the colours, type, and radii are CSS variables in
`src/styles/global.css`. It builds to static files, which the server
mounts after the API routes, so `/api/*` always reaches the API.

A static build cannot generate a page per upload id, so the pages
take ids as query parameters (`/upload?id=…`, `/live?upload=…&job=…`)
and load everything from the JSON API in the browser. The following
table describes the pages:

| Page | Shows |
|---|---|
| `index.astro` | The upload bar and the list of assessments. |
| `live.astro` | An assessment's progress, until it finishes. |
| `upload.astro` | The assessment: the host's details, the verdict and brief for each category with the findings behind it, the databases, and the Assess again button. |

`src/lib/api.ts` wraps the API calls for the upload bar, the list,
the progress page, and the Assess again button. `src/lib/follow.ts`
pairs the progress stream with a poll of the job, so the outcome is
reported once even if the stream drops. The assessment page's other
components call `fetch` directly.

## Testing

Tests are written before the code they test, and `run-ci-local.sh`
fails on any failing test. The suite has these kinds of test:

- Unit tests, one module per production module, with no I/O.
- Database tests, against the deployment's PostgreSQL image, which
  testcontainers starts once per session. `RADAR_ANALYST_PG_MAJOR`
  picks the major, 18 by default, and CI runs 16, 17, and 18. The
  fixture starts the server with UTF8 encoding and
  `logging_collector=off`, and each test drops the `radar` schema
  first.
- Adapter tests: Claude and OpenAI through a mock HTTP transport
  under the real SDK client, and Gemini and Ollama with their client
  factories replaced.
- A round trip from upload to assessment through
  `httpx.AsyncClient(ASGITransport(app))`, because `TestClient` closes
  its event loop when a request returns and so kills the background
  task.
- The end-to-end test, `test-radar-analyst.sh`. It brings up the
  compose stack with the mock provider, builds a sample archive
  inside the analyst's container, and assesses it. It then checks
  the verdicts, the progress stream over a real socket, the
  unprivileged PID 1, and the refused TCP connection to the database.
  After replacing the containers, it checks that the assessment and
  the archive are still there and that a delete with the admin token
  succeeds.
- `test_walkthrough_guide.py`, which runs the walkthrough against a
  stub `docker` and checks the commands it issues.

## Build and deployment

The Dockerfile has three stages: Node builds the console, Python
builds the wheel with the console inside it, and the runtime stage
installs only the wheel on `python:3.14-slim`. PostgreSQL runs as a
separate service.

The deployment is the image next to a PostgreSQL service:

```
docker compose up -d
        │
        ├── db   ghcr.io/pgedge/pgedge-postgres:18-spock5-minimal
        │          listen_addresses = localhost   (image default)
        │          POSTGRES_INITDB_ARGS = UTF8
        │          no published port
        │            ├── volume: db
        │            └── volume: sock → /run/postgresql
        │
        └── app  ghcr.io/pgedge/radar-analyst
                   docker-entrypoint.sh (root)
                     chown /data, setpriv → uid 10001
                   python -m radar_analyst
                     127.0.0.1:8080 published
                     ├── volume: archives → /data
                     └── volume: sock → /run/postgresql
                           connects host=/run/postgresql
```

The database has no TCP listener that anything else can reach. The
two containers share a volume holding the Unix socket, and nothing
else mounts it. Leaving the port unpublished would not be enough,
because a container's bridge address is routable from its host.

The `app` service maps `host.docker.internal` to the host gateway.
Docker Engine on Linux does not define that name, and the default
Ollama address uses it.

The pgEdge image's `initdb` defaults to SQL_ASCII, under which
psycopg returns every text column as `bytes`: a finished job never
reads as `done`, and the first rule to treat a value as a string
fails. The compose file sets UTF8. `store.db.check_server_encoding`
stops the analyst at startup on SQL_ASCII with one clear message,
and logs a warning for any other encoding that is not UTF8.
`store.db.wait_for_server` probes the database at a steady interval,
because the pool's own backoff can leave the analyst idle long after
the server is ready.

Both services log to stdout through Docker's json-file driver,
capped at three files of 10 MB each, and the database runs with
`logging_collector=off`, so no log grows inside a volume.

CI (`.github/workflows/ci.yml`) runs `run-ci-local.sh` once per
PostgreSQL major (16, 17, and 18) with fail-fast off. The script is
the whole pipeline: lint, type checks, tests, the console build, the
wheel, the image, and the end-to-end test.

## Memory

Every stage streams or caps what it reads. The following table shows
the most each stage holds in memory and the cap that bounds it:

| Stage | Peak in memory | Cap |
|---|---|---|
| Upload | Up to 1 MiB, because Starlette spools the rest of the body to a temporary file, and `routes_uploads.py::_bounded_stream` copies it on in chunks | `RADAR_ANALYST_MAX_UPLOAD_BYTES`, 500 MiB by default, applied as the upload is copied into the blob store |
| Blob store to temporary file | One 64 KiB chunk, in `blob.base.download_to_temp` | The upload cap |
| Reading the zip's directory | One `ZipInfo` per entry, which `zipfile` builds when it opens the archive | The upload cap. `archive/reader.py::list_entries` then refuses more than 100,000 entries, 2 GiB uncompressed, or 500 MiB in one entry, before anything is decompressed |
| Parsing an entry | Up to 1 MiB, in `analyze/parsing.py::read_and_parse` | A larger entry is skipped with a warning |
| Downloading an archive file | One 64 KiB chunk, in `GET /api/uploads/{id}/files/{path}`, which first copies the archive to a temporary file | None of its own |

## Known limits

The analyst has these limits:

- It cannot tell a configured setting from a default, because radar
  collects neither `boot_val` nor `source` from `pg_settings`, so the
  facts give a fixed list of settings with their values.
- It writes each brief from one category's facts; no step relates
  one category's findings to another's.
- It stores archives only on the local filesystem.
- It parses only the kinds `analyze/parsing.py` dispatches. The
  classifier recognises many more, such as pg_statviz's time series,
  Spock's per-database files, pgbouncer's configuration,
  pg_controldata output, and the cgroup, NUMA, and process listings,
  and the analyst ignores them.
- It is distributed only as a container image, because distributions
  do not package the provider SDKs.
