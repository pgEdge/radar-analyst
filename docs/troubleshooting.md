# Troubleshooting

This page describes common problems with pgEdge Radar Analyst and how to solve
each one. Most problems leave a message in the analyst's log, which Docker
keeps with the container. The following command shows the log of the analyst's
container:

```bash
docker compose logs app
```

Run the command in the directory that contains `docker-compose.yml`. The
[Getting Help](#getting-help) section describes how to report a problem that
this page does not cover.

## Starting the Analyst

The analyst checks its settings and its database at startup. The following
sections describe the problems that stop the analyst from starting.

### The Console Port Is Already in Use

The compose file publishes the console on port 8080 of the loopback interface.
When another service already uses that port, `docker compose up` fails. To use
another port, change the first port number in the `ports` entry of the `app`
service in `docker-compose.yml`. The following example publishes the console on
port 9090:

```yaml
    ports:
      - "127.0.0.1:9090:8080"
```

The console is then available at
[http://localhost:9090/](http://localhost:9090/). Keep 8080 as the second
number, because the analyst listens on that port inside the container.

### The Analyst Stops at Startup

At startup, the analyst waits up to 60 seconds for its database to accept
connections. Meanwhile, the log repeats the message
`waiting for the database at` with the address. When a startup check fails, the
analyst writes the reason to its log and stops. The following table describes
each message and how to fix the problem:

| Message in the log | Cause and fix |
|---|---|
| `unknown AI provider` | The `RADAR_ANALYST_AI_PROVIDER` setting names a provider that the analyst does not know. Set the variable to `claude`, `gemini`, `openai`, or `local`, in lowercase. |
| `Unknown level` | The `RADAR_ANALYST_LOG_LEVEL` setting names a log level that the analyst does not know. Set the variable to `DEBUG`, `INFO`, `WARNING`, or `ERROR`. |
| `did not accept a connection within 60s` | The analyst could not connect to its database within 60 seconds of starting. A wrong password in `RADAR_ANALYST_STATE_DB_URL` also ends in this message. Check the URL and check that the database is running. |
| `uses the SQL_ASCII encoding` | The state database uses the SQL_ASCII encoding, which the analyst cannot read. Create the database again with the UTF8 encoding. The bundled database uses UTF8, so the message concerns your own server. |
| `InsufficientPrivilege` | The role in the database URL lacks the `CREATE` privilege on the database. Grant the privilege to the role, then start the analyst again. |
| `invalid listen address` | The `RADAR_ANALYST_LISTEN` setting holds a malformed address. Use `host:port` or a bare port, and keep `0.0.0.0:8080` inside the container. |
| `RADAR_ANALYST_STATE_DB_URL is required` | The analyst started without `RADAR_ANALYST_STATE_DB_URL`, which only the compose file sets. Set the variable to the connection URL of the state database. |

## Writing Briefs

A provider writes the briefs, and the findings alone decide each verdict when
the provider fails. The following sections describe the problems that leave a
brief unavailable.

### A Brief Reads as Unavailable

When the provider fails, the brief reads "Brief unavailable for this category"
and gives the reason. A database brief reads "Brief unavailable for this
database" instead. The following table describes the common reasons:

| Reason in the brief | Cause and fix |
|---|---|
| `ANTHROPIC_API_KEY is not set` | The default `claude` provider has no credential in the `.env` file. Set the key, run `docker compose up -d --wait`, and press Assess again. |
| `GOOGLE_API_KEY / GEMINI_API_KEY is not set` | The `gemini` provider has no credential in the `.env` file. Set one of the keys, recreate the container, and press Assess again. |
| `OPENAI_API_KEY is not set` | The `openai` provider needs `OPENAI_API_KEY`, even for a server that ignores the key. Set the key, recreate the container, and press Assess again. |
| `call failed (auth)` | The provider rejected the credential as invalid or expired. Replace the key in the `.env` file and recreate the container. |
| `call failed (rate_limit)` | The provider refused the call because of a rate limit or quota. Wait, or raise the limit with the provider, then press Assess again. |
| `call failed (model_missing)` | The provider does not offer the model that the analyst requested. Set `OPENAI_MODEL` or `RADAR_ANALYST_OLLAMA_MODEL` to a model that the server provides. |
| `call failed (connection)` | The analyst could not reach the provider's service over the network. Check the network and, for `openai`, the address in `OPENAI_BASE_URL`. |
| `Failed to connect to Ollama` | The analyst could not reach the Ollama server for the `local` provider. The [Local Provider Cannot Reach Ollama](#the-local-provider-cannot-reach-ollama) section describes the fix. |
| `call failed (timeout)` | The Ollama server did not answer within 10 minutes. Check that the server runs. On slow hardware, lower `RADAR_ANALYST_OLLAMA_CONCURRENCY` so that fewer requests wait in the server's queue. |

The `GET /api/config` endpoint shows which providers have a credential set. The
endpoint does not test the credential, and always reports `local` as available.

### The Local Provider Cannot Reach Ollama

The `local` provider sends requests to the Ollama server at the address in
`RADAR_ANALYST_OLLAMA_HOST`. To solve a connection problem, make sure that:

- the Ollama server runs at the address in `RADAR_ANALYST_OLLAMA_HOST`.
- the server listens on an address that the analyst's container can reach.
- the server has the model, which `ollama pull` downloads.

Ollama listens only on `127.0.0.1` by default, which containers on Docker
Engine for Linux cannot reach. The
[Using a Local Ollama Server](index.md#using-a-local-ollama-server) section
describes the settings in more detail.

## Uploading Archives

The analyst refuses an upload that is empty, is not a zip archive, or is too
large. When an upload fails, the console shows the reason below the upload
form. The following table describes each message and how to fix the problem:

| Message | Cause and fix |
|---|---|
| `empty upload: not a zip archive` | The uploaded file contains no data at all. Upload the zip archive that radar wrote on the host. |
| `not a zip archive` | The uploaded file does not start like a zip archive. Upload the zip archive that radar wrote, not an extracted copy. |
| `upload exceeds max_upload_bytes` | The upload is larger than the upload limit, which is 500 MiB by default. Add `RADAR_ANALYST_MAX_UPLOAD_BYTES` with a higher value to the `environment` section of the `app` service. |
| `The upload did not reach the analyst.` | The console could not reach the analyst during the upload. Check that the analyst's container is running with `docker compose ps`. |

### An Assessment Has No Collection Time

The analyst reads the collection time from the name that radar gives the
archive, such as `radar-db1-20260903-164450.zip`. A renamed archive still gets
an assessment, but the assessment has no collection time. The host's name still
comes from the archive's contents, as for every archive. To keep the collection
time, upload the archive under the name that radar gave it.

## Assessing Archives

The following sections describe assessments that fail or take a long time.

### An Assessment Failed

The front page shows "Failed" for an assessment that did not finish, and the
assessment page shows the reason. The job's `error` field, which
`GET /api/jobs/{id}` returns, holds the same reason.

When the analyst stops during an assessment, the analyst marks the assessment
failed at the next start. The error then reads "the analyst stopped before this
assessment finished". To redo the assessment, open the assessment and press
Assess again.

While an assessment runs, the analyst refuses Assess again, and the console
shows "This upload is still being assessed." Wait for the assessment to finish,
then press Assess again.

### An Assessment Takes a Long Time

The analyst waits up to 10 minutes for each answer from the Ollama server. When
the server stalls, each brief reads as unavailable only after that wait. The
waits add up over the briefs of an assessment. To end the wait sooner, fix the
Ollama server, then restart the analyst with `docker compose restart app`. The
analyst marks the interrupted assessment failed, and Assess again redoes the
assessment.

## Deleting Assessments

The console asks for the admin token before the analyst deletes an assessment.
The following table describes the messages that the console can show:

| Message | Cause and fix |
|---|---|
| `The admin token was not accepted.` | The token that you entered does not match the analyst's admin token. Print the analyst's admin token with `docker compose exec app cat /data/admin-token`. When you set `RADAR_ANALYST_ADMIN_TOKEN`, enter that value in the prompt instead. |
| `Deleting is not configured on this analyst.` | The analyst has no admin token, because the analyst could not write the token file. The analyst's log shows `cannot write an admin token` at startup. Set `RADAR_ANALYST_ADMIN_TOKEN` in `.env` and run `docker compose up -d --wait`. |

## Running the Guided Walkthrough

The `examples/walkthrough/guide.sh` script checks Docker before the script
starts the analyst. The following table describes the messages that the script
prints when a check fails:

| Message | Cause and fix |
|---|---|
| `docker is not installed` | The `docker` command is not available on this machine. Install [Docker](https://docs.docker.com/get-started/get-docker/), then run the script again. |
| `Docker is installed but not running, or not reachable by your user.` | The Docker daemon is not running, or your user cannot use the daemon. Start Docker and check that `docker info` works for your user. |
| `The docker compose plugin is missing` | The `docker compose` command is not available on this machine. Install the [Compose plugin](https://docs.docker.com/compose/install/), then run the script again. |
| `docker compose up failed` | The script prints the last lines of the Compose output first. One cause is a port that another service already uses. The [Console Port Is Already in Use](#the-console-port-is-already-in-use) section describes that fix. |

## Getting Help

To report a problem that this page does not cover, open a
[GitHub issue](https://github.com/pgEdge/radar-analyst/issues). Include the
relevant lines of the analyst's log with the report. Before you post a log,
remove passwords, host names, and other private details. To report a security
vulnerability, follow the
[security policy](https://github.com/pgEdge/radar-analyst/security/policy)
instead of opening a public issue.
