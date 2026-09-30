# pgEdge Radar Analyst

pgEdge Radar Analyst assesses the health of a PostgreSQL host from a
[pgEdge Radar](https://github.com/pgEdge/radar) diagnostic archive.
The analyst checks the archive against deterministic rules, gives
each diagnostic category a verdict, and writes a brief that explains
the verdict. You read the assessment in a browser console, or fetch
it from a JSON API.

The analyst works from the uploaded archive alone. It never connects
to the host being assessed, and holds no credentials for it.

![An assessment in the console: the host's details, and PostgreSQL Configuration open on its verdict, brief, and findings](img/console-assessment-light.jpg#only-light)
![An assessment in the console: the host's details, and PostgreSQL Configuration open on its verdict, brief, and findings](img/console-assessment-dark.jpg#only-dark)

## Understanding an assessment

An assessment covers five diagnostic categories, and each category
answers one question about the host:

- Host & OS asks whether the machine is sized and tuned for a
  database workload.
- PostgreSQL Configuration asks whether the settings suit this
  hardware and this workload.
- Workload asks what the server is doing and whether anything is
  stuck.
- Internals & I/O Health asks whether the background processes, the
  WAL pipeline, and storage I/O are healthy.
- Replication asks whether replication is safe and caught up, and
  whether its WAL retention is under control.

Each category has a verdict of `HEALTHY`, `WARNING`, or `CRITICAL`,
the findings behind it, and a brief that explains them. Each brief
lists the archive files that its category covers. A category that
the archive holds no data for reads `UNKNOWN`.

The assessment's own verdict is the worst of the category verdicts.
`UNKNOWN` means that nothing was collected, so it never makes the
assessment's verdict worse than what was measured.

The assessment also has a card for each database on the server,
except template databases and databases that accept no connections.
A database with findings lists them and gets a brief of its own, and
a database without findings reads "No issues observed for this
database."

Findings are the issues that the analyst detects in the archive.
They are deterministic, and the same archive always produces the
same findings. A provider writes the briefs, and proposes a verdict
with each one. The analyst keeps a proposed verdict only when it is
at least as severe as the worst finding, so a provider can raise a
verdict but never lower it. Without a provider, or when the provider
cannot be reached, the findings alone decide each verdict, and each
brief reads as unavailable.

## Installing the analyst

The analyst runs as two containers: the analyst itself, and a
PostgreSQL database that holds its assessments. The only requirement
is Docker with the Compose plugin.

Save
[docker-compose.yml](https://github.com/pgEdge/radar-analyst/blob/main/docker-compose.yml)
into an empty directory, and start the analyst from that directory:

```bash
docker compose up -d --wait
```

The command returns once both containers are ready. If the image
pull is refused, sign in to the GitHub Container Registry with
`docker login ghcr.io`, using a token that can read packages, and
run the command again.

Open [http://localhost:8080/](http://localhost:8080/), drag a radar
archive onto the upload area or click the area to choose one, and
press Upload. The console shows the progress while the analyst reads
the archive and assesses each category, then opens the finished
assessment. The front page lists the 50 most recent assessments. Each
entry shows the host, the collection time, and the verdict, or
"Assessing…" while the assessment runs and "Failed" if it fails.

![The console's front page: the upload bar, and the list of assessments with each host, its collection time, and its verdict](img/console-front-page-light.jpg#only-light)
![The console's front page: the upload bar, and the list of assessments with each host, its collection time, and its verdict](img/console-front-page-dark.jpg#only-dark)

The analyst accepts zip archives of up to 500 MiB, and refuses any
other file at upload. The compose file publishes the console on
`127.0.0.1:8080`, so only your own machine can reach it, and the
database publishes no port at all.

To stop the analyst, run `docker compose stop`. To start it again,
with every upload and assessment in place, run
`docker compose start`. An assessment that was running when the
analyst stopped is marked failed when it starts again; open it and
press Assess again to redo it from the stored archive.

Radar collects the archive on the PostgreSQL host. The
[guided walkthrough](walkthrough.md) takes you from an empty
directory to an assessment of one of your own hosts, including
taking the collection. From a checkout of the repository,
`bash examples/walkthrough/guide.sh` runs the same tour
interactively and opens the console for you.

## Adding a provider for the briefs

The analyst works out the findings and verdicts from the archive
itself, and needs a provider only to write the briefs. To add one,
put its credential in a `.env` file beside `docker-compose.yml`, and
start the analyst again:

```bash
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env
docker compose up -d --wait
```

Assessments made before that keep their findings and verdicts. Open
one and press Assess again to have the briefs written from the
stored archive.

[examples/compose.env](https://github.com/pgEdge/radar-analyst/blob/main/examples/compose.env)
is a commented `.env` file to start from.
`RADAR_ANALYST_AI_PROVIDER` selects the provider and defaults to
`claude`. The following table describes the providers the analyst
supports:

| Provider | Service | Credential | Default model |
|---|---|---|---|
| `claude` | Anthropic | `ANTHROPIC_API_KEY` | `claude-sonnet-5` |
| `gemini` | Google AI Studio | `GOOGLE_API_KEY` or `GEMINI_API_KEY` | `gemini-3.7-flash` |
| `openai` | OpenAI, or an OpenAI-compatible server | `OPENAI_API_KEY` | `gpt-5.6-luna` |
| `local` | Ollama | None | `gemma4:e4b` |

The `claude` and `gemini` providers always use their default model.
`OPENAI_MODEL` chooses the model for `openai`, and
`RADAR_ANALYST_OLLAMA_MODEL` chooses it for `local`.

### OpenAI-compatible servers

The `openai` provider works with any server that implements the
OpenAI chat completions API, such as vLLM, LM Studio, llama.cpp,
OpenRouter, or Groq. Set the server's address and model name in
`.env`, and set `OPENAI_API_KEY` even when the server ignores it,
because the OpenAI client library requires a key:

```bash
RADAR_ANALYST_AI_PROVIDER=openai
OPENAI_BASE_URL=http://inference.example.com:8000/v1
OPENAI_API_KEY=unused
OPENAI_MODEL=Qwen/Qwen3-32B
```

The analyst runs in a container, so `localhost` in `OPENAI_BASE_URL`
refers to that container. Use an address the container can reach.

### A local Ollama server

The `local` provider sends its requests to the Ollama server at
`RADAR_ANALYST_OLLAMA_HOST`, so the briefs are written without
sending anything to an outside service. The compose file sets it to
`http://host.docker.internal:11434`, an Ollama server on the machine
that runs Docker, and maps that name itself, so the address works on
Docker Desktop and on Docker Engine for Linux alike. Point it at any
Ollama server that the analyst's container can reach.

The default model, `gemma4:e4b`, needs roughly 10 GB of GPU memory to
run entirely on the GPU, and runs more slowly on a smaller card.

## Using your own PostgreSQL

The analyst keeps its assessments in PostgreSQL. The compose file
includes a database for them, and the analyst can use a PostgreSQL
server you already run instead. The
compose file sets `RADAR_ANALYST_STATE_DB_URL` itself and ignores a
value in `.env`, so change the entry under the `app` service in
`docker-compose.yml` to your database's connection URL:

```yaml
      RADAR_ANALYST_STATE_DB_URL: postgresql://radar_analyst:PASSWORD@db.example.com:5432/radar_analyst?sslmode=require
```

To stop running the bundled database as well, remove the `db`
service and the `depends_on` entry that waits for it.

This database holds only the analyst's own state, and is never the
server being assessed. It must meet two conditions:

- It uses the UTF8 encoding. Under SQL_ASCII, PostgreSQL returns
  text as raw bytes, and the analyst refuses to start rather than
  misread its own rows. Any other encoding logs a warning at
  startup, because it can mangle text taken from a radar archive.
- The role in the URL has the CREATE privilege on the database,
  because the analyst creates a `radar` schema at startup and keeps
  all of its tables there.

## Managing your data

The compose stack uses three Docker volumes. The following table
describes what each volume holds:

| Volume | Holds |
|---|---|
| `db` | The assessments and their briefs |
| `archives` | The uploaded radar archives and the admin token |
| `sock` | The socket the analyst uses to reach the database |

The volumes outlive the containers. `docker compose down` and pulling
a newer image both leave them in place, and `docker compose down -v`
deletes them permanently.

Each service logs to `docker compose logs`. Docker keeps at most
three 10 MB log files for each service, 30 MB in all.

To keep the uploaded archives in a directory you can see, replace the
`archives` volume under the `app` service with that directory, and
keep the `sock` volume:

```yaml
    volumes:
      - /srv/radar-analyst:/data
      - sock:/run/postgresql
```

### Backing up

Stop the stack before copying the volumes, because a copy of a
running server's data directory is not consistent. These commands
write the database and the uploaded archives to
`radar-analyst-backup.tar.gz` in the current directory:

```bash
docker compose stop
docker run --rm -v radar-analyst_db:/db -v radar-analyst_archives:/archives \
    -v "$PWD:/backup" alpine \
    tar czf /backup/radar-analyst-backup.tar.gz /db /archives
docker compose start
```

Compose prefixes each volume name with the name of the directory that
holds the compose file, so these commands assume a directory named
`radar-analyst`. `docker volume ls` lists the actual names.

### Deleting an assessment

Each assessment in the console's list has a delete button. It asks
you to confirm, then asks for the admin token, which the console
remembers until the browser tab is closed. Deleting an assessment
also deletes its uploaded archive. The analyst generates the token
on first start and keeps it in the `archives` volume, and this
command prints it:

```bash
docker compose exec app cat /data/admin-token
```

To choose the token yourself, set `RADAR_ANALYST_ADMIN_TOKEN` in
`.env`. The analyst then accepts only that token, and ignores the one
in `/data/admin-token`.

## Environment variables

Every setting in this section is optional. The following table
describes the settings that the compose file reads from the `.env`
file beside `docker-compose.yml`:

| Variable | Default | Purpose |
|---|---|---|
| `RADAR_ANALYST_AI_PROVIDER` | `claude` | The provider that writes the briefs: `claude`, `gemini`, `openai`, or `local`; any other value stops the analyst at startup |
| `ANTHROPIC_API_KEY` | Unset | The credential for `claude` |
| `GOOGLE_API_KEY` or `GEMINI_API_KEY` | Unset | The credential for `gemini`; `GOOGLE_API_KEY` wins when both are set |
| `OPENAI_API_KEY` | Unset | The credential for `openai`, required even by a server that ignores it |
| `OPENAI_BASE_URL` | OpenAI's own endpoint | The address of an OpenAI-compatible server |
| `OPENAI_MODEL` | `gpt-5.6-luna` | The model for `openai`; a compatible server needs its own |
| `RADAR_ANALYST_OLLAMA_HOST` | `http://host.docker.internal:11434` | The Ollama server for `local` |
| `RADAR_ANALYST_OLLAMA_MODEL` | `gemma4:e4b` | The model for `local` |
| `RADAR_ANALYST_ADMIN_TOKEN` | Generated | The token that authorises deletes, generated into `/data/admin-token` on first start when unset |
| `RADAR_ANALYST_DB_PASSWORD` | `radar_analyst` | The password of the bundled database, which publishes no port |

The analyst also reads settings that the compose file does not pass
through. To set one of these, add it to the `environment` of the
`app` service in `docker-compose.yml`. The following table describes
them:

| Variable | Default | Purpose |
|---|---|---|
| `RADAR_ANALYST_MAX_UPLOAD_BYTES` | `524288000` (500 MiB) | The largest upload the analyst accepts, in bytes |
| `RADAR_ANALYST_OLLAMA_CONCURRENCY` | `3` | The most requests `local` sends to Ollama at once |
| `RADAR_ANALYST_LOG_LEVEL` | `INFO` | The log level |

The compose file sets `RADAR_ANALYST_STATE_DB_URL` itself, as
[Using your own PostgreSQL](#using-your-own-postgresql) describes.

## Using the API

The console reads everything it shows from a JSON API, and any other
client can use the same endpoints. The [API reference](api.md)
lists them. A running analyst serves an interactive browser for the
API at [http://localhost:8080/docs](http://localhost:8080/docs), and
the OpenAPI description at `/openapi.json`.

## Support and resources

To report a problem or request a feature, open an issue at
[github.com/pgEdge/radar-analyst/issues](https://github.com/pgEdge/radar-analyst/issues).
To report a security vulnerability, follow the
[security policy](https://github.com/pgEdge/radar-analyst/security/policy)
instead of opening a public issue. The pgEdge documentation is at
[docs.pgedge.com](https://docs.pgedge.com).

## Author

Written by Jimmy Angelakos.

## Licence

pgEdge Radar Analyst is released under the
[PostgreSQL Licence](LICENCE.md).
