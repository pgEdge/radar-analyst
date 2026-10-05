# API Reference

The console reads everything that it displays from the JSON API that this page
describes. Any other client can use the same endpoints. The
[openapi.json](api/openapi.json) file contains the machine-readable
description, which the analyst generates from its routes. The
[API browser](api/browser.md) page renders that description. A running analyst
serves the same description at `/openapi.json`, with interactive browsers at
[http://localhost:8080/docs](http://localhost:8080/docs) and
[http://localhost:8080/redoc](http://localhost:8080/redoc).

## Making an Assessment

An assessment through the API takes the following steps:

1. Upload the archive with `POST /api/uploads`. The request sends the radar
   archive as a multipart form field named `file`. The analyst stores the
   archive and returns `{upload_id, job_id}` with status 201.
2. Follow the job with `GET /api/jobs/{id}` until the job's `state` is `done`
   or `failed`. The [Jobs](#jobs) section describes the fields of a job.
3. Read the result with `GET /api/uploads/{id}/assessment`. The
   [Assessments](#assessments) section describes the response.

The following commands upload an archive, report the state of the job, and read
the finished assessment:

```bash
curl -F file=@radar-host-20260101-120000.zip http://localhost:8080/api/uploads
curl http://localhost:8080/api/jobs/<job_id>
curl http://localhost:8080/api/uploads/<upload_id>/assessment
```

The analyst returns status 415 for an upload that is empty or is not a zip
archive. For an upload larger than the limit in
`RADAR_ANALYST_MAX_UPLOAD_BYTES`, the analyst returns status 413.

### Following the Progress Stream

To follow a job without polling, read `GET /api/jobs/{id}/events`, which
streams the job's progress as Server-Sent Events. The stream sends each event
as an unnamed message whose `data` field holds a JSON object. The object's
`type` field names one of four events:

- `phase` marks the start of a stage and describes the stage in a `phase`
  field.
- `brief` reports a finished brief with the `category` and the category's
  `verdict`.
- `done` reports that the assessment finished, and the stream then closes.
- `error` reports in a `message` field that the assessment failed, and the
  stream then closes.

A client reads the `type` field of each message, because the stream does not
use named Server-Sent Events. A job that has already finished sends the final
`done` or `error` event at once. The following command follows the progress
stream of a job:

```bash
curl -N -H 'Accept: text/event-stream' \
    http://localhost:8080/api/jobs/<job_id>/events
```

## Endpoints

The following table lists every endpoint:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/uploads` | Uploads an archive and starts the assessment. |
| `GET` | `/api/uploads?limit=&offset=` | Lists the uploads, newest first. |
| `GET` | `/api/uploads/{id}` | Returns one upload. |
| `DELETE` | `/api/uploads/{id}` | Deletes an upload, the assessment, and the stored archive. |
| `POST` | `/api/uploads/{id}/assess` | Assesses the upload again from the stored archive. |
| `GET` | `/api/uploads/{id}/snapshot` | Returns the details that the analyst read from the archive. |
| `GET` | `/api/uploads/{id}/assessment` | Returns the verdict and the briefs. |
| `GET` | `/api/uploads/{id}/files` | Lists every entry in the archive. |
| `GET` | `/api/uploads/{id}/files/{path}` | Streams one entry of the archive. |
| `GET` | `/api/jobs/{id}` | Returns the state of a job. |
| `GET` | `/api/jobs/{id}/events` | Streams the progress of a job. |
| `GET` | `/api/config` | Lists the providers and their availability. |
| `GET` | `/healthz` | Returns `{"status": "ok"}` while the analyst process runs. |
| `GET` | `/readyz` | Returns `{"status": "ready"}` once the analyst has a database connection pool. The check does not query the database. |

## Uploads

The list endpoint returns the uploads in `items`, newest first, together with
the `limit` and `offset` that the analyst applied. The `limit` parameter
defaults to 50, and the analyst clamps the value to the range 1 to 500. The
`offset` parameter defaults to 0, and the analyst treats a negative value as 0.

The list endpoint and the single-upload endpoint return the same fields for
each upload. The following table describes the fields of an upload:

| Field | Description |
|---|---|
| `id` | Identifies the upload. |
| `filename` | Names the uploaded file. |
| `storage_url` | Locates the stored archive. |
| `size_bytes` | Records the size of the archive in bytes. |
| `sha256` | Records the SHA-256 digest of the archive. |
| `hostname` | Names the host that radar collected the archive on. |
| `archive_timestamp` | Records the collection time from the archive's name. |
| `created_at` | Records the upload time. |
| `state` | Reports the state of the most recent job for the upload. |
| `verdict` | Reports the roll-up verdict over the category briefs and the assessed databases. The verdict is `null` until the analyst stores the first brief. |

The analyst reads `hostname` and `archive_timestamp` from the archive's name at
upload. Once the analyst has read the archive, the analyst replaces `hostname`
with the host name that the archive records. Radar writes the host's local time
into the archive's name without a time zone. The `archive_timestamp` field
returns that local time with a UTC offset of zero.

## Jobs

A job assesses an upload in the background. `GET /api/jobs/{id}` returns status
404 for an unknown job. The following table describes the fields of a job:

| Field | Description |
|---|---|
| `id` | Identifies the job. |
| `upload_id` | Identifies the upload that the job assesses. |
| `state` | Reports the state of the job: `queued`, `parsing`, `analyzing`, `done`, or `failed`. |
| `phase` | Describes the most recent stage of the job. The field is `null` before the first stage and for a job that a stop interrupted. |
| `started_at` | Records the time that the job left the queue, or is `null` while the job waits. |
| `finished_at` | Records the time that the job finished, or is `null` until then. |
| `error` | Describes the failure when the job fails. |
| `ai_provider` | Names the provider that the analyst configured for the job. |

## Assessments

`GET /api/uploads/{id}/assessment` returns the roll-up `verdict` and a `briefs`
array with one entry per category. The roll-up is the worst of the category
verdicts and the database verdicts that the analyst has stored. Until the
analyst stores the first brief, the response has a `null` verdict and an empty
`briefs` array. The endpoint returns the same empty response for an upload ID
that does not exist.

The following table describes the fields of a brief:

| Field | Description |
|---|---|
| `id` | Identifies the brief. |
| `category` | Names the diagnostic category. |
| `verdict` | Reports the category verdict: `HEALTHY`, `WARNING`, `CRITICAL`, or `UNKNOWN`. |
| `findings` | Lists the findings behind the verdict. |
| `markdown` | Contains the text of the brief in Markdown. |
| `provider` | Names the provider that the analyst had configured when the analyst stored the brief. |
| `model` | Names the model that the analyst had configured when the analyst stored the brief. |
| `prompt_tokens` | Records the input token count that the provider reported, or is `null`. |
| `completion_tokens` | Records the output token count that the provider reported, or is `null`. |
| `created_at` | Records the time that the analyst stored the brief. |
| `sources` | Lists the archive files that the category covers. |

Each finding has a `rule_id`, a `severity` of `critical`, `warning`, or `info`,
a `title`, and a `detail`.

## Archive Details

`GET /api/uploads/{id}/snapshot` returns the details that the analyst read from
the archive. The endpoint returns status 404 until the analyst has read the
archive. The response describes:

- the host, in `hostname`, `os`, `kernel`, `cpu_count`, `cpu_model`,
  `total_ram`, and `host_uptime`.
- where the host runs, in `is_container`, `hypervisor`, `runtime`, and
  `cloud_provider`.
- the PostgreSQL server, in `pg_version` and `pg_started`.
- the radar release that took the collection, in `radar_version` and
  `radar_commit`.
- each database with its counters and findings, in `databases`.
- the kinds of data that the analyst read from the archive, in `parsed_kinds`.
- the archive paths that the analyst did not recognize, in `unknown_entries`.

Each entry in `databases` gains `brief_markdown` and `brief_verdict` once the
analyst has assessed the databases.

## Archive Files

`GET /api/uploads/{id}/files` lists every entry in the uploaded archive in
`items`. Each entry has a `path`, a `kind`, a `dbname`, and a `size`. An entry
that the analyst does not recognize has `null` for all but the `path`. The
listing stays empty until the analyst has read the archive.

`GET /api/uploads/{id}/files/{path}` streams one entry as an attachment. The
analyst sends `.tsv` entries as `text/tab-separated-values` and `.out`,
`.conf`, `.done`, and `.txt` entries as `text/plain`. Every other entry has the
type `application/octet-stream`.

The listing acts as an allowlist for `GET /api/uploads/{id}/files/{path}`. The
analyst refuses any path outside the listing with status 404, including any
path traversal attempt.

## Deleting an Upload

`DELETE /api/uploads/{id}` requires the admin token as a bearer credential in
the `Authorization` header. The request removes the upload, the assessment, and
the stored archive, and returns status 204. The analyst refuses a request
without a valid token with status 401. When the analyst has no admin token, the
analyst refuses every delete with status 503. The analyst has no admin token
when, for example, the data directory is not writable. The
[Deleting an Assessment](index.md#deleting-an-assessment) section describes
where the admin token comes from. The following command deletes an upload with
the token in `TOKEN`:

```bash
curl -X DELETE -H "Authorization: Bearer $TOKEN" \
    http://localhost:8080/api/uploads/<upload_id>
```

## Assessing an Upload Again

`POST /api/uploads/{id}/assess` assesses the upload again from the stored
archive, for example after you configure a provider. The request removes the
previous briefs and findings, creates a new job, and returns
`{upload_id, job_id}` with status 202. Follow the new job in the same way as a
job that an upload starts. While a job for the upload is queued or in progress,
the analyst refuses the request with status 409.

At startup, the analyst marks every job that had not finished at the previous
stop as `failed`. The `error` field of each such job explains the interruption.

## Providers

`GET /api/config` lists the providers in `providers` and returns `default`, the
provider that the analyst uses when `RADAR_ANALYST_AI_PROVIDER` is unset. Each
provider entry has a `name`, a `label`, an `available` flag, and a `model`. The
provider names are `claude`, `gemini`, `openai`, and `local`. An unavailable
provider also has a `reason`, which names the missing setting. The `local`
provider has no setting to check, so the `local` provider always reports as
available. When `RADAR_ANALYST_TEST` is `1`, the list also includes the `mock`
provider that the end-to-end tests use.

## Errors

The following table describes the error statuses that the API returns:

| Status | Meaning |
|---|---|
| 401 | The delete request has no valid admin token. |
| 404 | The upload, job, archive details, or archive entry does not exist, or no route matches the path. |
| 409 | A job for the upload is still queued or in progress. |
| 413 | The upload is larger than the upload limit. |
| 415 | The upload is empty or is not a zip archive. |
| 422 | The request is malformed, for example with a missing `file` field or an invalid ID. |
| 503 | The analyst has no admin token and refuses every delete. |
