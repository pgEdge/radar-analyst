# pgEdge Radar Analyst

pgEdge Radar Analyst reads a
[radar](https://github.com/pgEdge/radar) diagnostic archive and
returns an assessment of the PostgreSQL host it came from. The
analyst checks the archive against deterministic rules and writes a
short brief for each diagnostic category, then serves the result over
a browser console and a JSON API.

## What you need

Docker, with the Compose plugin. Nothing else: the analyst and the
PostgreSQL it keeps its own state in both come up as containers.

## Quick start

Save `docker-compose.yml` from the repository into an empty
directory, then:

```bash
docker compose up -d
```

Open [http://localhost:8080/](http://localhost:8080/) and drag a
`radar-*.zip` onto the upload area. The analyst reads the archive,
applies the rules, and returns the assessment in the console. A file
that is not a zip archive is refused at upload time.

Both images live in the pgEdge container registry. If the pull is
refused, sign in first with a token that can read packages:

```bash
docker login ghcr.io
```

The compose file publishes the console on `127.0.0.1:8080`, so it is
reachable only from your own machine, and gives the database no
published port at all.

To stop it, `docker compose stop`. To bring it back,
`docker compose start`. Your uploads and their assessments are still
there.

## Adding a provider for the briefs

The assessment works without one: the findings and verdicts are
computed from the archive and come back either way. A provider adds
the written brief for each category. Put a credential in a `.env`
file next to `docker-compose.yml`:

```bash
echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env
docker compose up -d
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

The stack keeps three Docker volumes:

| Volume | Holds |
|---|---|
| `db` | the assessments, findings, and briefs |
| `archives` | the radar archives you uploaded, and the admin token |
| `sock` | the socket the analyst talks to the database over |

The database has no network port at all. The analyst reaches it
through that shared socket, so nothing else on your machine can
connect to it.

Replacing the containers keeps all of it. `docker compose down`
followed by `docker compose up -d`, which is what upgrading does,
gives you new containers reading the same volumes.

Logs go to `docker compose logs`, capped at three files of 10 MB per
service, so they cannot grow until the disk is full.

The first two outlive the containers. `docker compose down` leaves them in
place, and so does pulling a newer image. `docker compose down -v` is
what deletes them.

To keep the uploaded archives somewhere you can see, replace the
`archives` volume in the compose file with a directory of your own:

```yaml
    volumes:
      - /home/you/radar-analyst:/data
```

### Backing up

Stop the stack first: copying a running server's data directory does
not give a consistent snapshot.

```bash
docker compose stop
docker run --rm -v radar-analyst_db:/db -v radar-analyst_archives:/archives \
    -v "$PWD:/backup" alpine \
    tar czf /backup/radar-analyst-backup.tar.gz /db /archives
docker compose start
```

The volume names are prefixed with the directory the compose file
lives in; `docker volume ls` shows the real ones.

## Deleting an assessment

The delete button in the console asks for an admin token. The analyst
generates one on first start and keeps it in the archives volume:

```bash
docker compose exec app cat /data/admin-token
```

Paste it into the prompt. To choose the token yourself, set
`RADAR_ANALYST_ADMIN_TOKEN` in your `.env` file.

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
that URL names instead of the one in the compose file. This is the
database the analyst keeps its own state in, never the server being
assessed: the analyst works from the uploaded archive and holds no
credentials for the assessed host.

The database must use the UTF8 encoding. Under SQL_ASCII, PostgreSQL
hands text back as raw bytes and the analyst refuses to start rather
than misreading its own rows.

## Environment variables

The settings the analyst reads from its environment. The README
documents the full list.

Everything is optional. `docker-compose.yml` supplies the database
URL, and without a provider credential you still get the findings
and the verdicts.

`RADAR_ANALYST_STATE_DB_URL`
: PostgreSQL for the analyst's own state, never the assessed
  server. Set by the compose file. Must be a UTF8 database.

`RADAR_ANALYST_DATA_DIR`
: Where uploaded archives and the admin token are kept. `/data` in
  the image.

`RADAR_ANALYST_AI_PROVIDER`
: `claude`, `gemini`, `openai`, or `local`. Defaults to `claude`.

`RADAR_ANALYST_ADMIN_TOKEN`
: Bearer token required to delete an upload. Generated into
  `/data/admin-token` when unset.

`RADAR_ANALYST_DB_PASSWORD`
: Password for the database service. Defaults to `radar_analyst`,
  which is safe because the database has no reachable port.

`ANTHROPIC_API_KEY`
: Required when the provider is `claude`.

`GOOGLE_API_KEY`
: Required when the provider is `gemini`.

`OPENAI_API_KEY`
: Required when the provider is `openai`, including for compatible
  servers that ignore the value.

`OPENAI_BASE_URL`
: Point this at an OpenAI-compatible server, for example
  `http://localhost:8000/v1`. Defaults to OpenAI's own endpoint.

`OPENAI_MODEL`
: Model name. A compatible server needs its own, for example
  `Qwen/Qwen3-32B`. Defaults to `gpt-5.6-luna`.

`RADAR_ANALYST_OLLAMA_HOST`
: Used when the provider is `local`. Defaults to
  `http://localhost:11434`.

`RADAR_ANALYST_OLLAMA_MODEL`
: Used when the provider is `local`. Defaults to `gemma4:e4b`,
  which needs roughly 10 GB of VRAM to run fully on GPU.

## Author

Written by Jimmy Angelakos.

## Licence

See [LICENCE](LICENCE.md). The PostgreSQL Licence.
