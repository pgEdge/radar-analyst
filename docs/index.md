# pgEdge Radar Analyst

pgEdge Radar Analyst assesses the health of a PostgreSQL host from a
[pgEdge Radar](https://github.com/pgEdge/radar) diagnostic archive. The analyst
checks the archive against deterministic rules and gives each diagnostic
category a verdict. For each category, the analyst also writes a brief that
explains the verdict. You can read each assessment in the analyst's web console
or retrieve the assessment from a JSON API.

The analyst works from the uploaded archive alone. The analyst never connects
to the assessed host and holds no credentials for that host.

![An assessment in the console: the host's details, and PostgreSQL Configuration open on its verdict, brief, and findings](img/console-assessment-light.jpg#only-light)
![An assessment in the console: the host's details, and PostgreSQL Configuration open on its verdict, brief, and findings](img/console-assessment-dark.jpg#only-dark)

## Understanding an Assessment

An assessment covers five diagnostic categories, and each category answers one
question about the host:

- Host & OS asks whether the machine's size and tuning suit a database
  workload.
- PostgreSQL Configuration asks whether the server settings suit the hardware
  and the workload.
- Workload asks what the server is doing and whether any work has stalled.
- Internals & I/O Health asks whether the background processes, the write-ahead
  log pipeline, and storage I/O are healthy.
- Replication asks whether replication is safe and caught up, and whether
  write-ahead log retention is under control.

Each category has a verdict of `HEALTHY`, `WARNING`, or `CRITICAL`. A category
also shows the findings behind the verdict and a brief that explains those
findings. Each brief lists the archive files that the category covers. A
category for which the archive holds no data has the verdict `UNKNOWN`.

The verdict of the assessment as a whole is the worst of the category verdicts
and the database verdicts. `UNKNOWN` means only that the archive holds no data
for a category. An `UNKNOWN` category therefore never makes the overall verdict
worse than the measured evidence.

The assessment also includes a card for each database on the server. Template
databases and databases that accept no connections have no card. The card for a
database with findings lists those findings and includes a brief for that
database. The card for a database without findings reads "No issues observed
for this database." Each database card shows a verdict of its own. That verdict
counts toward the overall verdict once the analyst has assessed the databases.

Findings are the issues that the analyst's deterministic rules detect in the
archive. The same archive always produces the same findings. A provider writes
each brief and proposes a verdict along with the brief. The analyst keeps a
proposed verdict only when that verdict is at least as severe as the worst
finding. A provider can therefore raise a verdict but never lower one. Without
a provider, or when the provider fails, the findings alone decide each verdict.
In that case, the briefs read as unavailable. The
[Adding a Provider for the Briefs](#adding-a-provider-for-the-briefs) section
describes the supported providers.

## Installing the Analyst

The analyst runs as two containers: the analyst itself and a PostgreSQL
database that stores the assessments. The only requirement is
[Docker](https://docs.docker.com/get-started/get-docker/) with the
[Compose plugin](https://docs.docker.com/compose/install/).

To install the analyst, save
[docker-compose.yml](https://github.com/pgEdge/radar-analyst/blob/main/docker-compose.yml)
into an empty directory and run the following command in that directory:

```bash
docker compose up -d --wait
```

The command returns once both containers are ready, and the console is then
available at [http://localhost:8080/](http://localhost:8080/). The compose file
publishes the console on `127.0.0.1:8080`, so only the local machine can reach
the console. The database publishes no port at all.

To stop the analyst, run `docker compose stop`. To start the analyst again with
every upload and assessment in place, run `docker compose start`. At startup,
the analyst marks any assessment that was still running at the previous stop as
failed. To redo such an assessment from the stored archive, open the assessment
and press Assess again.

## Assessing a Radar Archive

Radar collects the diagnostic archive on the PostgreSQL host, and you then
upload the archive to the analyst. The [guided walkthrough](walkthrough.md)
describes how to take a radar collection. The walkthrough covers every step
from an empty directory to a finished assessment.

From a clone of the
[pgEdge/radar-analyst](https://github.com/pgEdge/radar-analyst) repository, the
following command runs the same tour interactively:

```bash
bash examples/walkthrough/guide.sh
```

The guide also opens the console for you.

To assess an archive in the console, perform the following steps:

1. Open [http://localhost:8080/](http://localhost:8080/) in a browser on the
   machine that runs the analyst.
2. Drag the radar archive onto the upload area, or click the upload area and
   choose the archive.
3. Press Upload to send the archive to the analyst.

The console shows the progress while the analyst reads the archive and assesses
each category. When the assessment finishes, the console opens the result. The
analyst accepts zip archives of up to 500 MiB and refuses any other file at
upload.

The front page of the console lists the 50 most recent uploads, newest first.
Each entry shows the host, the file name and size, the collection time, the
status, and the upload time. The status is the verdict, "Assessing…" while the
assessment runs, or "Failed" if the assessment fails. The collection time comes
from the name that radar gives the archive, so a renamed archive has no
collection time.

![The console's front page: the upload bar, and the list of assessments with each host, its collection time, and its verdict](img/console-front-page-light.jpg#only-light)
![The console's front page: the upload bar, and the list of assessments with each host, its collection time, and its verdict](img/console-front-page-dark.jpg#only-dark)

To redo an assessment from the stored archive, open the assessment, press
Assess again, and confirm. The new result replaces the previous result.
Assessing again is useful after you configure a provider, or after a stop
interrupts an assessment.

## Adding a Provider for the Briefs

The analyst derives the findings, and a verdict for every category, from the
archive itself. A provider writes the briefs and can raise a verdict, as
[Understanding an Assessment](#understanding-an-assessment) describes. To add a
provider, set `RADAR_ANALYST_AI_PROVIDER` and the provider's credential in a
`.env` file beside `docker-compose.yml`. Then start the analyst again to apply
the settings. The default provider, `claude`, needs only a credential. Add the
following line to the `.env` file, and create the file if the file does not
exist:

```bash
ANTHROPIC_API_KEY=sk-ant-...
```

The following command recreates the analyst's container with the new setting:

```bash
docker compose up -d --wait
```

Existing assessments keep their findings and verdicts. To add briefs to an
existing assessment, open the assessment and press Assess again.

The
[examples/compose.env](https://github.com/pgEdge/radar-analyst/blob/main/examples/compose.env)
file is a commented template for the `.env` file. The
`RADAR_ANALYST_AI_PROVIDER` setting selects the provider and defaults to
`claude`. The following table describes the supported providers:

| Provider | Service | Credential | Default model |
|---|---|---|---|
| `claude` | [Anthropic](https://platform.claude.com/) | `ANTHROPIC_API_KEY` | `claude-sonnet-5` |
| `gemini` | [Google AI Studio](https://aistudio.google.com/) | `GOOGLE_API_KEY` or `GEMINI_API_KEY` | `gemini-3.7-flash` |
| `openai` | [OpenAI](https://platform.openai.com/), or an OpenAI-compatible server | `OPENAI_API_KEY` | `gpt-5.6-luna` |
| `local` | [Ollama](https://ollama.com/) | None | `gemma4:e4b` |

The `claude` and `gemini` providers always use the default model in the table.
The `OPENAI_MODEL` setting selects the model for `openai`, and
`RADAR_ANALYST_OLLAMA_MODEL` selects the model for `local`. Every provider
other than `claude` also needs `RADAR_ANALYST_AI_PROVIDER` set to the
provider's name. The following `.env` lines select Google AI Studio:

```bash
RADAR_ANALYST_AI_PROVIDER=gemini
GOOGLE_API_KEY=...
```

### Using an OpenAI-Compatible Server

The `openai` provider works with any server that implements the OpenAI chat
completions API. Such servers include [vLLM](https://docs.vllm.ai/),
[LM Studio](https://lmstudio.ai/),
[llama.cpp](https://github.com/ggml-org/llama.cpp),
[OpenRouter](https://openrouter.ai/), and [Groq](https://groq.com/). To use
such a server, set the server's address and model name in `.env`. Set
`OPENAI_API_KEY` even when the server ignores the key, because the OpenAI
client library requires a key. The following `.env` file selects a server at
`inference.example.com`:

```bash
RADAR_ANALYST_AI_PROVIDER=openai
OPENAI_BASE_URL=http://inference.example.com:8000/v1
OPENAI_API_KEY=unused
OPENAI_MODEL=Qwen/Qwen3-32B
```

Inside the analyst's container, `localhost` in `OPENAI_BASE_URL` refers to that
container rather than the machine that runs Docker. Use an address that the
analyst's container can reach.

### Using a Local Ollama Server

The `local` provider sends requests to an [Ollama](https://ollama.com/) server
that you run, at the address in `RADAR_ANALYST_OLLAMA_HOST`. The analyst then
writes the briefs without sending data to an outside service. The following
`.env` line selects the provider:

```bash
RADAR_ANALYST_AI_PROVIDER=local
```

The compose file sets `RADAR_ANALYST_OLLAMA_HOST` to
`http://host.docker.internal:11434`, which addresses an Ollama server on the
machine that runs Docker. The compose file maps the `host.docker.internal` name
itself. The name therefore resolves on both Docker Desktop and Docker Engine
for Linux. On Docker Engine for Linux, the Ollama server must also listen on an
address that containers can reach. Ollama listens only on `127.0.0.1` by
default, and the `OLLAMA_HOST` environment variable of the Ollama server
changes that address. To use a different Ollama server, set
`RADAR_ANALYST_OLLAMA_HOST` in `.env` to an address that the analyst's
container can reach.

The Ollama server must already have the model, because the analyst does not
download models. The following command downloads the default model on the
Ollama server:

```bash
ollama pull gemma4:e4b
```

The default model needs approximately 10 GB of GPU memory to run entirely on
the GPU. The model runs more slowly on a GPU with less memory.

## Using Your Own PostgreSQL Server

The analyst stores its assessments in PostgreSQL. The compose file includes a
database for this purpose, but the analyst can use an existing PostgreSQL
server instead. The compose file sets `RADAR_ANALYST_STATE_DB_URL` directly and
ignores any value in `.env`. To use your own server, edit the
`RADAR_ANALYST_STATE_DB_URL` entry under the `app` service in
`docker-compose.yml`. Set the entry to the connection URL of your database:

```yaml
      RADAR_ANALYST_STATE_DB_URL: >-
        postgresql://radar_analyst:PASSWORD@db.example.com/radar_analyst?sslmode=require
```

To stop running the bundled database, also remove the `db` service from the
compose file. Then remove the `depends_on` entry that waits for the `db`
service.

This database holds only the analyst's own state and is never the server under
assessment. The database must meet two conditions:

- The database uses the UTF8 encoding, which the analyst checks at startup.
  Under SQL_ASCII, PostgreSQL returns text as raw bytes, so the analyst refuses
  to start rather than misread its own rows. With any other encoding, the
  analyst logs a warning. Such an encoding may not represent all text in a
  radar archive correctly.
- The role in the URL has the `CREATE` privilege on the database. The analyst
  needs the privilege because the analyst creates a `radar` schema for all of
  its tables at startup.

## Managing Your Data

The compose file defines three Docker volumes. The following table describes
the contents of each volume:

| Volume | Contents |
|---|---|
| `db` | Holds the state database, which stores every assessment. |
| `archives` | Holds the uploaded radar archives and the admin token. |
| `sock` | Holds the socket that the analyst uses to connect to the database. |

The volumes outlive the containers, so running `docker compose down` or pulling
a newer image leaves the volumes in place. However, `docker compose down -v`
deletes the volumes permanently.

Each service writes its log to the container output, which
`docker compose logs` displays. Docker keeps at most three 10 MB log files for
each service. Each service therefore uses no more than 30 MB for logs.

To keep the uploaded archives in a host directory, replace the `archives`
volume of the `app` service with that directory. Keep the `sock` volume, as the
following example shows:

```yaml
    volumes:
      - /srv/radar-analyst:/data
      - sock:/run/postgresql
```

The analyst's container runs the analyst as user ID 10001. At startup, when
that user does not own the directory, the container recursively changes the
directory's owner to that user.

### Backing Up Your Data

A backup copies the state database and the uploaded archives out of the Docker
volumes. Stop the stack before copying the volumes, because a copy of a running
server's data directory is not consistent. The following commands write the
database and the uploaded archives to `radar-analyst-backup.tar.gz` in the
current directory:

```bash
docker compose stop
docker run --rm -v radar-analyst_db:/db -v radar-analyst_archives:/archives \
    -v "$PWD:/backup" alpine \
    tar czf /backup/radar-analyst-backup.tar.gz /db /archives
docker compose start
```

Compose prefixes each volume name with the name of the directory that holds the
compose file. These commands therefore assume a directory named
`radar-analyst`. Run `docker volume ls` to list the actual volume names.

### Deleting an Assessment

Each entry in the console's list of assessments has a delete button. The button
asks for confirmation and then for the admin token. The console remembers the
token until you close the browser tab. Deleting an assessment also deletes the
uploaded archive.

The analyst generates the admin token on first start and stores the token in
the `archives` volume. The following command prints the admin token:

```bash
docker compose exec app cat /data/admin-token
```

To choose the token yourself, set `RADAR_ANALYST_ADMIN_TOKEN` in `.env` and run
`docker compose up -d --wait` again. The analyst then accepts only that token
and ignores the token in `/data/admin-token`.

## Configuring the Analyst

The analyst reads its configuration from environment variables, and every
setting in this section is optional. The following table describes the settings
that the compose file reads from the `.env` file beside `docker-compose.yml`:

| Variable | Default | Purpose |
|---|---|---|
| `RADAR_ANALYST_AI_PROVIDER` | `claude` | Selects the provider that writes the briefs: `claude`, `gemini`, `openai`, or `local`. Any other value stops the analyst at startup. |
| `ANTHROPIC_API_KEY` | Unset | Sets the credential for `claude`. |
| `GOOGLE_API_KEY` or `GEMINI_API_KEY` | Unset | Sets the credential for `gemini`. When both are set, `GOOGLE_API_KEY` takes precedence. |
| `OPENAI_API_KEY` | Unset | Sets the credential for `openai`. The OpenAI client library requires a key, even for a server that ignores the key. |
| `OPENAI_BASE_URL` | OpenAI's own endpoint | Sets the address of an OpenAI-compatible server. |
| `OPENAI_MODEL` | `gpt-5.6-luna` | Selects the model for `openai`. A compatible server needs the name of a model that the server provides. |
| `RADAR_ANALYST_OLLAMA_HOST` | `http://host.docker.internal:11434` | Sets the address of the Ollama server for `local`. |
| `RADAR_ANALYST_OLLAMA_MODEL` | `gemma4:e4b` | Selects the model for `local`. |
| `RADAR_ANALYST_ADMIN_TOKEN` | Generated | Sets the token that authorizes deletes. When the variable is unset, the analyst generates a token into `/data/admin-token` on first start. |
| `RADAR_ANALYST_DB_PASSWORD` | `radar_analyst` | Sets the password of the bundled database when the `db` volume is first initialized. The database publishes no port. |

The analyst also reads the following settings, which the compose file does not
pass through from `.env`. To change one of these settings, add the variable to
the `environment` section of the `app` service in `docker-compose.yml`. The
following table describes these settings:

| Variable | Default | Purpose |
|---|---|---|
| `RADAR_ANALYST_MAX_UPLOAD_BYTES` | `524288000` (500 MiB) | Sets the largest upload that the analyst accepts, in bytes. An invalid value logs a warning, and the analyst uses the default. |
| `RADAR_ANALYST_OLLAMA_CONCURRENCY` | `3` | Sets the maximum number of requests that `local` sends to Ollama at once, as a positive integer. The analyst ignores a value that is not an integer. |
| `RADAR_ANALYST_LOG_LEVEL` | `INFO` | Sets the log level, such as `DEBUG`, `INFO`, `WARNING`, or `ERROR`, in any letter case. An unknown level stops the analyst at startup. |

The compose file sets `RADAR_ANALYST_STATE_DB_URL` directly, as
[Using Your Own PostgreSQL Server](#using-your-own-postgresql-server)
describes.

## Using the API

The console reads everything that it displays from a JSON API, and any other
client can use the same endpoints. The [API reference](api.md) describes each
endpoint that the API provides. The [API browser](api/browser.md) page renders
the OpenAPI description of the API for browsing. A running analyst also serves
an interactive browser at
[http://localhost:8080/docs](http://localhost:8080/docs) and the description
itself at `/openapi.json`.

## Support & Resources

For more information about pgEdge products, visit
[docs.pgedge.com](https://docs.pgedge.com).

To report an issue or request a feature, visit
[GitHub Issues](https://github.com/pgEdge/radar-analyst/issues). To report a
security vulnerability, follow the
[security policy](https://github.com/pgEdge/radar-analyst/security/policy)
instead of opening a public issue.

The [changelog](changelog.md) lists the changes in each release.

## Author

Jimmy Angelakos created pgEdge Radar Analyst.

## License

This project is licensed under the [PostgreSQL License](LICENSE.md).
