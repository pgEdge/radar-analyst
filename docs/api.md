# API

The console is a pure consumer of this API, so anything that speaks
the same endpoints can replace it.

The machine-readable description is
[openapi.json](openapi.json), generated from the routes themselves.
It cannot go stale: a test compares it against the running
application and fails if the two disagree.

A running analyst also serves it live, with an interactive browser
at [http://localhost:8080/docs](http://localhost:8080/docs) and the
raw document at `/openapi.json`.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/api/uploads` | Upload an archive |
| `GET` | `/api/uploads` | List prior uploads |
| `GET` | `/api/uploads/{id}` | Upload metadata |
| `DELETE` | `/api/uploads/{id}` | Delete an upload |
| `GET` | `/api/uploads/{id}/snapshot` | Parsed context |
| `GET` | `/api/uploads/{id}/assessment` | Verdict and briefs |
| `GET` | `/api/uploads/{id}/files` | Archive inventory |
| `GET` | `/api/uploads/{id}/files/{path}` | One archive entry |
| `GET` | `/api/jobs/{id}` | Job state |
| `GET` | `/api/jobs/{id}/events` | Progress stream |
| `GET` | `/api/config` | Providers available |
| `GET` | `/healthz` | Liveness |
| `GET` | `/readyz` | Readiness |

Uploading returns `{upload_id, job_id}`. A body that is not a zip
archive is refused with 415. Deleting requires the admin token as a
bearer credential.

Each upload in the list, and the single upload, carries `hostname`
and `archive_timestamp`, read from radar's archive name at upload
and confirmed from the archive once it has been read, plus the
`state` of its most recent job and the roll-up `verdict` over its
briefs, `null` until the first brief lands.
