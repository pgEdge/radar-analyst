# pgEdge Radar Analyst

pgEdge Radar Analyst reads a
[radar](https://github.com/pgEdge/radar) diagnostic archive and
returns an assessment of the PostgreSQL host it came from. The
analyst checks the archive against deterministic rules and writes a
short brief for each diagnostic category, then serves the result over
a browser console and a JSON API.

## What you need

Docker. Nothing else.

The analyst ships as a single container image with its own
PostgreSQL server inside it, so there is no database to install, no
configuration file to write, and nothing to clone.

## Quick start

```bash
docker run -d --name radar-analyst \
    -p 127.0.0.1:8080:8080 \
    -v radar-analyst-data:/data \
    ghcr.io/pgedge/radar-analyst
```

Open [http://localhost:8080/](http://localhost:8080/) and drag a
`radar-*.zip` onto the upload area. The analyst reads the archive,
applies the rules, and returns the assessment in the console. A file
that is not a zip archive is refused at upload time.

The `-p 127.0.0.1:8080:8080` is what keeps the analyst reachable only
from your own machine. Dropping the `127.0.0.1` prefix would publish
it on every network interface of the host.

The image is published to the pgEdge container registry. If the pull
is refused, sign in first with a token that can read packages:

```bash
docker login ghcr.io
```

## Adding a provider for the briefs

The assessment works without one: findings and verdicts are computed
from the archive and come back either way. A provider adds the
written brief for each category. Set one of these when you start the
container:

```bash
docker run -d --name radar-analyst \
    -p 127.0.0.1:8080:8080 \
    -v radar-analyst-data:/data \
    -e ANTHROPIC_API_KEY=sk-ant-... \
    ghcr.io/pgedge/radar-analyst
```

The analyst supports these providers:

- Anthropic, by setting `ANTHROPIC_API_KEY`.
- Google AI Studio, by setting `GOOGLE_API_KEY`.
- OpenAI, by setting `OPENAI_API_KEY`. Point `OPENAI_BASE_URL` at
  any OpenAI-compatible server to use one instead.
- A local Ollama server, by setting `RADAR_ANALYST_AI_PROVIDER=local`
  and pointing `RADAR_ANALYST_OLLAMA_HOST` at it.

Set `RADAR_ANALYST_AI_PROVIDER` to `claude`, `gemini`, `openai`, or
`local` to choose between them. It defaults to `claude`.

## Where your data is kept

Everything the analyst keeps lives in the one volume you mounted at
`/data`:

| Path | Holds |
|---|---|
| `/data/archives` | the radar archives you uploaded |
| `/data/db` | the assessments, findings, and briefs |
| `/data/admin-token` | the token that authorises a delete |

The volume outlives the container. Replacing the container, pulling a
newer image, or restarting the machine leaves your uploads and their
assessments in place. Removing the volume is what deletes them.

To keep the archives somewhere you can see them, mount a directory
from your own machine instead of a named volume:

```bash
-v "$HOME/radar-analyst:/data"
```

### Backing up

Stop the container first: copying a running server's data directory
does not give a consistent snapshot.

```bash
docker stop radar-analyst
docker run --rm -v radar-analyst-data:/data -v "$PWD:/backup" \
    alpine tar czf /backup/radar-analyst-backup.tar.gz -C /data .
docker start radar-analyst
```

Restore into an empty volume the same way, with `tar xzf`.

### Upgrading

```bash
docker pull ghcr.io/pgedge/radar-analyst
docker rm -f radar-analyst
docker run -d --name radar-analyst ...   # same -v, same volume
```

A PostgreSQL data directory is bound to the major version that
created it. If a future image ships a different major, the analyst
refuses to start and names both versions rather than failing part
way through.

## Deleting an assessment

The delete button in the console asks for an admin token. The
analyst generates one on first start and keeps it in the volume:

```bash
docker exec radar-analyst cat /data/admin-token
```

Paste it into the prompt. To choose the token yourself, set
`RADAR_ANALYST_ADMIN_TOKEN` when you start the container.

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

## Using your own PostgreSQL

Set `RADAR_ANALYST_STATE_DB_URL` and the analyst uses the database
that URL names instead of starting its own. This is the database the
analyst keeps its own state in, never the server being assessed: the
analyst works from the uploaded archive and holds no credentials for
the assessed host.

```bash
docker run -d --name radar-analyst \
    -p 127.0.0.1:8080:8080 \
    -v radar-analyst-data:/data \
    -e RADAR_ANALYST_STATE_DB_URL=postgresql://user:pw@dbhost:5432/radar_analyst \
    ghcr.io/pgedge/radar-analyst
```

Archives still land in `/data/archives`, so the volume is still
worth mounting. The repository's `docker-compose.yml` runs this
arrangement with a PostgreSQL service alongside the analyst.

## Environment variables

The following table describes the settings the analyst reads from
its environment. The README documents the full list.

| Variable | Default | Purpose |
|---|---|---|
| `RADAR_ANALYST_DATA_DIR` | `/data` | the one directory holding archives, the database, and the admin token |
| `RADAR_ANALYST_STATE_DB_URL` | _(unset)_ | use this PostgreSQL for the analyst's own state instead of the bundled server; never the assessed server |
| `RADAR_ANALYST_AI_PROVIDER` | `claude` | `claude`, `gemini`, `openai`, or `local` |
| `RADAR_ANALYST_ADMIN_TOKEN` | _(generated)_ | bearer token required to delete an upload; generated into `/data/admin-token` when unset |
| `RADAR_ANALYST_LISTEN` | `0.0.0.0:8080` in the image | listen address inside the container; what keeps the analyst local is the `127.0.0.1` prefix on the published port |
| `ANTHROPIC_API_KEY` | _(unset)_ | required when the provider is `claude` |
| `GOOGLE_API_KEY` | _(unset)_ | required when the provider is `gemini` |
| `OPENAI_API_KEY` | _(unset)_ | required when the provider is `openai`, including for compatible servers that ignore the value |
| `OPENAI_BASE_URL` | OpenAI's own endpoint | set to reach an OpenAI-compatible server, for example `http://localhost:8000/v1` |
| `OPENAI_MODEL` | `gpt-5.6-luna` | model name; a compatible server needs its own, for example `Qwen/Qwen3-32B` |
| `RADAR_ANALYST_OLLAMA_HOST` | `http://localhost:11434` | used when the provider is `local` |
| `RADAR_ANALYST_OLLAMA_MODEL` | `gemma4:e4b` | used when the provider is `local`; needs roughly 10 GB of VRAM to run fully on GPU |

## Licence

See [LICENCE](LICENCE.md). The PostgreSQL Licence.
