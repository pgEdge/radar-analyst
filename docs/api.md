# API

The console reads everything it shows from this API, and any other
client can use the same endpoints. The machine-readable description
is [openapi.json](openapi.json), generated from the routes
themselves. A running analyst serves the same document at
`/openapi.json`, with an interactive browser at
[http://localhost:8080/docs](http://localhost:8080/docs).

## How an assessment is made

Every assessment follows the same sequence of calls:

1. `POST /api/uploads` takes the radar archive as a multipart form
   field named `file`, stores it, and returns `{upload_id, job_id}`
   with status 201. A body that is not a zip archive is refused with
   415, and one larger than the upload limit with 413.
2. The job assesses the archive in the background.
   `GET /api/jobs/{id}` reports its `state`, which is `queued`,
   `running`, `done`, or `failed`, the pipeline `phase` while it
   runs, its timestamps, and the `error` when it failed.
3. `GET /api/jobs/{id}/events` streams the job's progress as
   Server-Sent Events: a `phase` event as each stage begins, a
   `brief` event as each category's brief is written, and a final
   `done` or `error` event, after which the stream closes. A job
   that has already finished gets its final event at once.
4. `GET /api/uploads/{id}/assessment` returns the result: the
   roll-up `verdict`, and a `briefs` array with one entry per
   category holding its `verdict`, its `findings` (each with
   `rule_id`, `severity`, `title`, and `detail`), its `markdown`,
   the `provider` and `model` that wrote it, and `sources`, the
   archive files the category covers.
5. `GET /api/uploads/{id}/snapshot` returns what the analyst read
   from the archive: the host and its PostgreSQL version, the
   `databases` list with each database's counters, findings, and
   brief, the file kinds it parsed, and `unknown_entries`, the
   archive paths it did not recognise.

## Endpoints

The following table lists every endpoint:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/uploads` | Upload an archive and start its assessment |
| `GET` | `/api/uploads?limit=&offset=` | List uploads, newest first |
| `GET` | `/api/uploads/{id}` | One upload |
| `DELETE` | `/api/uploads/{id}` | Delete an upload, its assessment, and its archive |
| `POST` | `/api/uploads/{id}/assess` | Assess the upload again from its stored archive |
| `GET` | `/api/uploads/{id}/snapshot` | What was read from the archive |
| `GET` | `/api/uploads/{id}/assessment` | The verdict and the briefs |
| `GET` | `/api/uploads/{id}/files` | Every entry in the archive |
| `GET` | `/api/uploads/{id}/files/{path}` | One entry of the archive |
| `GET` | `/api/jobs/{id}` | The state of a job |
| `GET` | `/api/jobs/{id}/events` | The progress stream of a job |
| `GET` | `/api/config` | The providers and their availability |
| `GET` | `/healthz` | Liveness |
| `GET` | `/readyz` | Readiness: the database pool is attached |

## Uploads

Each upload in the list, and the single upload, has `hostname` and
`archive_timestamp`, read from the archive's name at upload and
confirmed from the archive once it has been read, the `state` of its
most recent job, and its roll-up `verdict`, which is `null` until
the first brief is written. `limit` defaults to 50 and is clamped to
1-500.

## Archive files

`GET /api/uploads/{id}/files` lists every entry of the uploaded
archive, and `GET /api/uploads/{id}/files/{path}` streams one entry.
The listing is the whitelist: a path that is not in it, including
any traversal attempt, is refused with 404. The listing is empty
until the archive has been read.

## Deleting

`DELETE /api/uploads/{id}` requires the admin token as a bearer
credential in the `Authorization` header. It removes the upload, its
assessment, and its stored archive, and returns 204. Without the
token the request is refused with 401, and while the analyst has no
token at all, with 503.

## Assessing again

`POST /api/uploads/{id}/assess` assesses the upload again from its
stored archive, for example once a provider has been configured. It
removes the previous briefs and findings, creates a new job, and
returns `{upload_id, job_id}` with status 202, to follow as after an
upload. While an assessment of the upload is still running, the
request is refused with 409.

A job that was running when the analyst stopped is marked `failed`
at the next start, with an `error` that says so.

## Providers

`GET /api/config` lists the providers. Each entry has `name`,
`label`, `available`, and `model`, and an unavailable provider also
has a `reason` naming the setting it lacks.
